<?php
/*
Plugin Name: Hamnaghsheh Bot Bridge
Description: REST API bridge between the Bale bot and WordPress/Hamnaghsheh systems.
Version: 1.0.0
Author: Soroush Yasini
*/

if (!defined('ABSPATH')) exit;

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────

define('HN_BOT_SECRET_KEY_OPTION', 'hn_bot_secret_key');

// On activation, generate a secret key if one doesn't exist
register_activation_hook(__FILE__, function () {
    if (!get_option(HN_BOT_SECRET_KEY_OPTION)) {
        update_option(HN_BOT_SECRET_KEY_OPTION, bin2hex(random_bytes(32)));
    }

    // Create bale_user_id column in wp_users if it doesn't exist
    global $wpdb;
    $exists = $wpdb->get_var("SHOW COLUMNS FROM {$wpdb->users} LIKE 'bale_user_id'");
    if (!$exists) {
        $wpdb->query("ALTER TABLE {$wpdb->users} ADD bale_user_id BIGINT NULL UNIQUE");
    }
});

// ─────────────────────────────────────────────
// ADMIN PAGE — show the secret key
// ─────────────────────────────────────────────

add_action('admin_menu', function () {
    add_submenu_page(
        'hamnaghsheh-orders',
        'تنظیمات بات',
        'تنظیمات بات',
        'manage_options',
        'hn-bot-settings',
        'hn_bot_settings_page'
    );
});

function hn_bot_settings_page() {
    $key = get_option(HN_BOT_SECRET_KEY_OPTION, '(هنوز تولید نشده)');
    echo '<div class="wrap">';
    echo '<h1>تنظیمات بات بله</h1>';
    echo '<p>این کلید را در فایل <code>config.py</code> بات قرار دهید:</p>';
    echo '<code style="font-size:16px;padding:10px;display:block;background:#f0f0f0;">' . esc_html($key) . '</code>';
    echo '<p style="color:red;">این کلید را مثل رمز عبور نگهداری کنید.</p>';

    // Regenerate
    if (isset($_POST['regenerate']) && check_admin_referer('hn_bot_regen')) {
        update_option(HN_BOT_SECRET_KEY_OPTION, bin2hex(random_bytes(32)));
        echo '<p style="color:green;">کلید جدید تولید شد. صفحه را رفرش کنید.</p>';
    }

    echo '<form method="post">';
    wp_nonce_field('hn_bot_regen');
    echo '<input type="submit" name="regenerate" class="button button-secondary" value="تولید کلید جدید">';
    echo '</form></div>';
}

// ─────────────────────────────────────────────
// AUTH HELPER
// ─────────────────────────────────────────────

function hn_bot_verify_request(WP_REST_Request $request): bool {
    $secret = get_option(HN_BOT_SECRET_KEY_OPTION, '');
    $provided = $request->get_header('X-Bot-Secret');
    return hash_equals($secret, (string) $provided);
}

function hn_bot_auth_error() {
    return new WP_Error('forbidden', 'Unauthorized', ['status' => 403]);
}

// ─────────────────────────────────────────────
// REST ROUTES
// ─────────────────────────────────────────────

add_action('rest_api_init', function () {
    $ns = 'bot/v1';

    // Check if mobile exists
    register_rest_route($ns, '/check-user', [
        'methods'             => 'POST',
        'callback'            => 'hn_bot_check_user',
        'permission_callback' => '__return_true',
    ]);

    // Send OTP
    register_rest_route($ns, '/send-otp', [
        'methods'             => 'POST',
        'callback'            => 'hn_bot_send_otp',
        'permission_callback' => '__return_true',
    ]);

    // Verify OTP → returns user info + one-time login URL
    register_rest_route($ns, '/verify-otp', [
        'methods'             => 'POST',
        'callback'            => 'hn_bot_verify_otp',
        'permission_callback' => '__return_true',
    ]);

    // Link bale_user_id to wp user (called after successful verify)
    register_rest_route($ns, '/link-bale-user', [
        'methods'             => 'POST',
        'callback'            => 'hn_bot_link_bale_user',
        'permission_callback' => '__return_true',
    ]);

    // Get services list
    register_rest_route($ns, '/services', [
        'methods'             => 'GET',
        'callback'            => 'hn_bot_get_services',
        'permission_callback' => '__return_true',
    ]);

    // Get user orders
    register_rest_route($ns, '/orders/(?P<wp_user_id>\d+)', [
        'methods'             => 'GET',
        'callback'            => 'hn_bot_get_orders',
        'permission_callback' => '__return_true',
    ]);

    // Get single order detail
    register_rest_route($ns, '/order/(?P<order_id>\d+)', [
        'methods'             => 'GET',
        'callback'            => 'hn_bot_get_order',
        'permission_callback' => '__return_true',
    ]);

    // Generate one-time login URL for a user
    register_rest_route($ns, '/login-url', [
        'methods'             => 'POST',
        'callback'            => 'hn_bot_generate_login_url',
        'permission_callback' => '__return_true',
    ]);

    // Notify: WP → bot push (called by WP hooks, bot receives on its webhook)
    // This route isn't for the bot to call — it's a dummy confirmer.
    // The real notification goes the other direction: WP calls the bot's API.
    // See: hn_bot_push_notification() below.

    // Admin: get pending orders count (for admin bot notifications)
    register_rest_route($ns, '/admin/pending-orders', [
        'methods'             => 'GET',
        'callback'            => 'hn_bot_admin_pending_orders',
        'permission_callback' => '__return_true',
    ]);
});

// ─────────────────────────────────────────────
// ENDPOINT HANDLERS
// ─────────────────────────────────────────────

/**
 * POST /bot/v1/check-user
 * Body: { mobile }
 * Returns: { exists, has_password, first_name }
 */
function hn_bot_check_user(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    global $wpdb;
    $mobile = sanitize_text_field($request->get_param('mobile'));
    $mobile = hn_convert_persian_numbers($mobile);

    if (!hn_is_valid_mobile($mobile)) {
        return new WP_Error('invalid_mobile', 'فرمت شماره موبایل نامعتبر است', ['status' => 400]);
    }

    $user = $wpdb->get_row($wpdb->prepare(
        "SELECT ID, display_name FROM {$wpdb->users} WHERE mobile = %s", $mobile
    ));

    if (!$user) {
        return rest_ensure_response(['exists' => false, 'has_password' => false, 'first_name' => '']);
    }

    $has_password = get_user_meta($user->ID, 'mobile_auth_has_password', true) === '1';

    return rest_ensure_response([
        'exists'       => true,
        'has_password' => $has_password,
        'first_name'   => $user->display_name,
        'wp_user_id'   => $user->ID,
    ]);
}

/**
 * POST /bot/v1/send-otp
 * Body: { mobile }
 * Returns: { sent, rate_limit_remaining }
 */
function hn_bot_send_otp(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    $mobile = sanitize_text_field($request->get_param('mobile'));
    $mobile = hn_convert_persian_numbers($mobile);

    if (!hn_is_valid_mobile($mobile)) {
        return new WP_Error('invalid_mobile', 'فرمت شماره موبایل نامعتبر است', ['status' => 400]);
    }

    // Rate limit check
    $remaining = hn_check_otp_rate_limit($mobile);
    if ($remaining > 0) {
        return rest_ensure_response(['sent' => false, 'rate_limit_remaining' => $remaining]);
    }

    $code = rand(100000, 999999);
    set_transient('otp_' . $mobile, $code, 180);          // 3 min
    set_transient('otp_rate_limit_' . $mobile, time(), 60); // 1 min cooldown

    // Send via Kavenegar (reuse mobile-auth logic)
    hn_send_otp_sms($mobile, $code);

    return rest_ensure_response(['sent' => true, 'rate_limit_remaining' => 0]);
}

/**
 * POST /bot/v1/verify-otp
 * Body: { mobile, code, bale_user_id }
 * Returns: { success, wp_user_id, display_name, is_new_user, login_url }
 */
function hn_bot_verify_otp(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    global $wpdb;
    $mobile       = hn_convert_persian_numbers(sanitize_text_field($request->get_param('mobile')));
    $code         = hn_convert_persian_numbers(sanitize_text_field($request->get_param('code')));
    $bale_user_id = sanitize_text_field($request->get_param('bale_user_id'));

    $saved = get_transient('otp_' . $mobile);
    if (!$saved || $saved != $code) {
        return new WP_Error('wrong_otp', 'کد تأیید نادرست یا منقضی شده است', ['status' => 400]);
    }

    delete_transient('otp_' . $mobile);

    // Get or create user
    $user_id = $wpdb->get_var($wpdb->prepare(
        "SELECT ID FROM {$wpdb->users} WHERE mobile = %s", $mobile
    ));

    $is_new_user = false;
    if (!$user_id) {
        $is_new_user = true;
        $user_id = wp_insert_user([
            'user_login' => 'u' . $mobile,
            'user_pass'  => wp_generate_password(),
            'user_email' => $mobile . '@auth.local',
        ]);
        $wpdb->update($wpdb->users, ['mobile' => $mobile], ['ID' => $user_id]);
    }

    // Link bale_user_id
    if ($bale_user_id) {
        $wpdb->update($wpdb->users, ['bale_user_id' => $bale_user_id], ['ID' => $user_id]);
    }

    $user = get_userdata($user_id);

    // Generate one-time login URL
    $login_url = hn_generate_magic_login_url($user_id, site_url('/'));

    return rest_ensure_response([
        'success'      => true,
        'wp_user_id'   => $user_id,
        'display_name' => $user->display_name,
        'is_new_user'  => $is_new_user,
        'login_url'    => $login_url,
    ]);
}

/**
 * POST /bot/v1/link-bale-user
 * Body: { wp_user_id, bale_user_id }
 */
function hn_bot_link_bale_user(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    global $wpdb;
    $wp_user_id   = intval($request->get_param('wp_user_id'));
    $bale_user_id = sanitize_text_field($request->get_param('bale_user_id'));

    $result = $wpdb->update($wpdb->users, ['bale_user_id' => $bale_user_id], ['ID' => $wp_user_id]);

    return rest_ensure_response(['linked' => $result !== false]);
}

/**
 * GET /bot/v1/services
 */
function hn_bot_get_services(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    $services = Hamnaghsheh_Services::get_active_services();
    $result = [];
    foreach ($services as $s) {
        $result[] = [
            'id'          => $s->id,
            'key'         => $s->service_key,
            'name'        => $s->service_name_fa,
            'price'       => (int) $s->price_per_session,
            'description' => $s->description,
            'image_url'   => $s->image_url,
        ];
    }
    return rest_ensure_response($result);
}

/**
 * GET /bot/v1/orders/{wp_user_id}
 */
function hn_bot_get_orders(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    $wp_user_id = intval($request->get_param('wp_user_id'));
    $orders = Hamnaghsheh_Orders::get_user_orders($wp_user_id);

    $result = [];
    foreach ($orders as $o) {
        $result[] = [
            'id'             => $o->id,
            'order_number'   => $o->order_number,
            'service_type'   => $o->service_type,
            'status'         => $o->status,
            'status_label'   => Hamnaghsheh_Orders::get_status_label($o->status),
            'quantity'       => $o->requested_quantity,
            'total_price'    => $o->final_price ? (int)$o->final_price : (int)$o->requested_total_price,
            'created_at'     => $o->created_at,
            'order_url'      => site_url('/order/?order_id=' . $o->id),
            'payment_needed' => $o->status === 'awaiting_payment',
        ];
    }
    return rest_ensure_response($result);
}

/**
 * GET /bot/v1/order/{order_id}
 */
function hn_bot_get_order(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    $order_id = intval($request->get_param('order_id'));
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);

    if (!$o) return new WP_Error('not_found', 'سفارش یافت نشد', ['status' => 404]);

    $service = Hamnaghsheh_Services::get_service_by_key($o->service_type);

    return rest_ensure_response([
        'id'             => $o->id,
        'order_number'   => $o->order_number,
        'service_name'   => $service ? $service->service_name_fa : $o->service_type,
        'status'         => $o->status,
        'status_label'   => Hamnaghsheh_Orders::get_status_label($o->status),
        'quantity'       => $o->requested_quantity,
        'address'        => $o->address,
        'area_size'      => $o->area_size,
        'phone'          => $o->phone,
        'final_price'    => $o->final_price ? (int)$o->final_price : null,
        'requested_total_price' => (int)$o->requested_total_price,
        'admin_notes'    => $o->admin_notes,
        'created_at'     => $o->created_at,
        'order_url'      => site_url('/order/?order_id=' . $o->id),
        'payment_needed' => $o->status === 'awaiting_payment',
        'user_id'        => $o->user_id,
    ]);
}

/**
 * POST /bot/v1/login-url
 * Body: { wp_user_id, redirect_to (optional) }
 * Returns: { url }
 */
function hn_bot_generate_login_url(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    $wp_user_id  = intval($request->get_param('wp_user_id'));
    $redirect_to = esc_url_raw($request->get_param('redirect_to') ?? site_url('/'));

    $url = hn_generate_magic_login_url($wp_user_id, $redirect_to);
    return rest_ensure_response(['url' => $url]);
}

/**
 * GET /bot/v1/admin/pending-orders
 */
function hn_bot_admin_pending_orders(WP_REST_Request $request) {
    if (!hn_bot_verify_request($request)) return hn_bot_auth_error();

    global $wpdb;
    $table  = $wpdb->prefix . 'hamnaghsheh_orders';
    $counts = $wpdb->get_results(
        "SELECT status, COUNT(*) as cnt FROM {$table} GROUP BY status"
    );

    $result = [];
    foreach ($counts as $row) {
        $result[$row->status] = (int)$row->cnt;
    }
    return rest_ensure_response($result);
}

// ─────────────────────────────────────────────
// PUSH NOTIFICATIONS: WP → Bot
// Hooked into existing Hamnaghsheh action hooks
// ─────────────────────────────────────────────

add_action('hamnaghsheh_new_order',        'hn_bot_notify_admin_new_order');
add_action('hamnaghsheh_price_set',        'hn_bot_notify_user_price_set');
add_action('hamnaghsheh_payment_confirmed','hn_bot_notify_user_payment_confirmed');
add_action('hamnaghsheh_project_created',  'hn_bot_notify_user_project_created');
add_action('hamnaghsheh_order_completed',  'hn_bot_notify_user_order_completed');
// Status change catch-all
add_action('hamnaghsheh_order_submitted',  function($order_id) {
    // notify admin
    hn_bot_notify_admin_new_order($order_id);
});

/**
 * Notify admin(s) about a new order
 */
function hn_bot_notify_admin_new_order($order_id) {
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);
    if (!$o) return;

    $service = Hamnaghsheh_Services::get_service_by_key($o->service_type);
    $service_name = $service ? $service->service_name_fa : $o->service_type;

    $text = "🆕 *سفارش جدید*\n\n"
          . "📋 شماره: `{$o->order_number}`\n"
          . "🗺️ خدمت: {$service_name}\n"
          . "📦 تعداد: {$o->requested_quantity}\n"
          . "💰 مبلغ درخواستی: " . number_format($o->requested_total_price) . " تومان\n"
          . "📍 آدرس: {$o->address}\n\n"
          . "برای مشاهده جزئیات دستور /order_{$order_id} را ارسال کنید";

    hn_bot_push_to_admins($text, $order_id);
}

/**
 * Notify user: price set / awaiting payment
 */
function hn_bot_notify_user_price_set($order_id) {
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);
    if (!$o) return;

    $price = number_format((int)$o->final_price);
    $text  = "💰 *قیمت نهایی سفارش شما تعیین شد*\n\n"
           . "📋 سفارش: `{$o->order_number}`\n"
           . "💳 مبلغ: {$price} تومان\n\n"
           . "لطفاً برای پرداخت وارد حساب کاربری شوید.";

    hn_bot_push_to_user($o->user_id, $text, [
        ['text' => '💳 پرداخت آنلاین', 'url' => site_url('/order/?order_id=' . $order_id)],
    ]);
}

/**
 * Notify user: payment confirmed
 */
function hn_bot_notify_user_payment_confirmed($order_id) {
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);
    if (!$o) return;

    $text = "✅ *پرداخت شما تأیید شد*\n\n"
          . "📋 سفارش: `{$o->order_number}`\n"
          . "🗺️ عملیات نقشه‌برداری به زودی شروع خواهد شد.\n"
          . "از طریق همین بات وضعیت سفارش را دنبال کنید.";

    hn_bot_push_to_user($o->user_id, $text);
}

/**
 * Notify user: project created / in progress
 */
function hn_bot_notify_user_project_created($order_id) {
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);
    if (!$o) return;

    $text = "🗺️ *عملیات نقشه‌برداری شروع شد*\n\n"
          . "📋 سفارش: `{$o->order_number}`\n"
          . "پروژه شما ایجاد شد و تیم در حال برنامه‌ریزی است.\n"
          . "نتایج از طریق پورتال در دسترس خواهد بود.";

    hn_bot_push_to_user($o->user_id, $text, [
        ['text' => '📂 مشاهده پروژه', 'url' => site_url('/my-orders/')],
    ]);
}

/**
 * Notify user: order completed
 */
function hn_bot_notify_user_order_completed($order_id) {
    $o = Hamnaghsheh_Orders::get_order_by_id($order_id);
    if (!$o) return;

    $text = "🎉 *سفارش شما تکمیل شد*\n\n"
          . "📋 سفارش: `{$o->order_number}`\n"
          . "نتایج نقشه‌برداری آماده است. از پورتال دانلود کنید.";

    hn_bot_push_to_user($o->user_id, $text, [
        ['text' => '📥 دانلود نتایج', 'url' => site_url('/my-orders/')],
    ]);
}

// ─────────────────────────────────────────────
// PUSH HELPERS
// ─────────────────────────────────────────────

/**
 * Push a message to a WP user's linked Bale account
 */
function hn_bot_push_to_user(int $wp_user_id, string $text, array $inline_buttons = []) {
    global $wpdb;
    $bale_user_id = $wpdb->get_var($wpdb->prepare(
        "SELECT bale_user_id FROM {$wpdb->users} WHERE ID = %d", $wp_user_id
    ));
    if (!$bale_user_id) return; // user hasn't linked their Bale account

    $bot_url = get_option('hn_bot_api_url', ''); // e.g. http://your-bot-server:8000/internal/push
    if (!$bot_url) return;

    $payload = [
        'bale_user_id'   => $bale_user_id,
        'text'           => $text,
        'inline_buttons' => $inline_buttons,
    ];

    wp_remote_post($bot_url, [
        'headers' => [
            'Content-Type'  => 'application/json',
            'X-Bot-Secret'  => get_option(HN_BOT_SECRET_KEY_OPTION, ''),
        ],
        'body'    => wp_json_encode($payload),
        'timeout' => 5,
    ]);
}

/**
 * Push a message to all admin Bale accounts
 */
function hn_bot_push_to_admins(string $text, int $order_id = 0) {
    $admin_bale_ids = get_option('hn_bot_admin_bale_ids', []); // array of bale_user_ids
    if (empty($admin_bale_ids)) return;

    $bot_url = get_option('hn_bot_api_url', '');
    if (!$bot_url) return;

    $buttons = [];
    if ($order_id) {
        $buttons[] = ['text' => '🔍 مشاهده سفارش', 'url' => admin_url('admin.php?page=hamnaghsheh-order-detail&order_id=' . $order_id)];
    }

    foreach ((array)$admin_bale_ids as $bale_id) {
        wp_remote_post($bot_url, [
            'headers' => [
                'Content-Type' => 'application/json',
                'X-Bot-Secret' => get_option(HN_BOT_SECRET_KEY_OPTION, ''),
            ],
            'body'    => wp_json_encode([
                'bale_user_id'   => $bale_id,
                'text'           => $text,
                'inline_buttons' => $buttons,
            ]),
            'timeout' => 5,
        ]);
    }
}

// ─────────────────────────────────────────────
// MAGIC LOGIN URL
// One-time URL: bot → user taps → logged into site
// ─────────────────────────────────────────────

add_action('init', 'hn_bot_handle_magic_login');

function hn_generate_magic_login_url(int $user_id, string $redirect_to = ''): string {
    $token = bin2hex(random_bytes(24));
    set_transient('hn_magic_login_' . $token, ['user_id' => $user_id, 'redirect_to' => $redirect_to], 300); // 5 min
    return site_url('/') . '?hn_magic_token=' . $token;
}

function hn_bot_handle_magic_login() {
    if (!isset($_GET['hn_magic_token'])) return;

    $token = sanitize_text_field($_GET['hn_magic_token']);
    $data  = get_transient('hn_magic_login_' . $token);

    if (!$data || empty($data['user_id'])) {
        wp_redirect(site_url('/auth?err=expired_token'));
        exit;
    }

    delete_transient('hn_magic_login_' . $token);

    wp_set_current_user($data['user_id']);
    wp_set_auth_cookie($data['user_id']);

    $redirect_to = !empty($data['redirect_to']) ? $data['redirect_to'] : home_url('/');
    wp_redirect($redirect_to);
    exit;
}

// ─────────────────────────────────────────────
// UTILITY FUNCTIONS (mirrors mobile-auth.php)
// ─────────────────────────────────────────────

function hn_convert_persian_numbers(string $string): string {
    $persian = ['٠','١','٢','٣','٤','٥','٦','٧','٨','٩','۰','۱','۲','۳','۴','۵','۶','۷','۸','۹'];
    $english = ['0','1','2','3','4','5','6','7','8','9','0','1','2','3','4','5','6','7','8','9'];
    return str_replace($persian, $english, $string);
}

function hn_is_valid_mobile(string $mobile): bool {
    return (bool) preg_match('/^09\d{9}$/', $mobile);
}

function hn_check_otp_rate_limit(string $mobile): int {
    $last = get_transient('otp_rate_limit_' . $mobile);
    if ($last !== false) {
        $remaining = 60 - (time() - $last);
        if ($remaining > 0) return $remaining;
    }
    return 0;
}

function hn_send_otp_sms(string $mobile, int $code) {
    sleep(1); // slight delay, bot context so no page hang
    $url = "https://api.kavenegar.com/v1/75414544654B737133454E4A6D336D485645346C797A43356D676B6648632B5736372B384E524A4E4954343D/verify/lookup.json?" .
        http_build_query([
            'receptor' => $mobile,
            'token'    => $code,
            'template' => 'login',
        ]);
    wp_remote_get($url);
}
