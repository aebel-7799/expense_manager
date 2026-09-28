package com.aebel.expensemanager;

import android.os.Bundle;
import android.webkit.CookieManager;

import com.getcapacitor.BridgeActivity;

/**
 * The app is a Capacitor WebView pointed at the live Expense Manager site
 * (see server.url in capacitor.config.json), so "staying logged in" depends
 * entirely on the WebView's cookie store.
 *
 * The server sends the login session as a cookie with an explicit Expires/Max-Age
 * (the session is marked permanent), which makes it a persistent cookie that the
 * WebView writes to disk. The two things below make that reliable:
 *   - cookies are explicitly accepted, and
 *   - the store is flushed to disk as soon as the app is backgrounded, so the
 *     login is already on disk when Android kills the process (swiping the app
 *     away from recents, or reclaiming memory).
 *
 * Restoring "Cleared from RAM" therefore restores the login. Clearing app data
 * from Android Settings still wipes the cookie store, which correctly requires
 * logging in again.
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(SaveFilePlugin.class);
        CookieManager.getInstance().setAcceptCookie(true);
        super.onCreate(savedInstanceState);
    }

    @Override
    public void onResume() {
        super.onResume();
        CookieManager.getInstance().setAcceptCookie(true);
        if (getBridge() != null && getBridge().getWebView() != null) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(getBridge().getWebView(), true);
        }
    }

    @Override
    public void onPause() {
        // Force the WebView to write its cookies to disk *before* the app can be
        // backgrounded/killed. Without this, Android may drop the Flask session
        // cookie when it reclaims the app's process and logs the user out.
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    public void onStop() {
        // onStop is the last callback that runs before Android tears the process
        // down, so flush again as a safety net.
        CookieManager.getInstance().flush();
        super.onStop();
    }
}
