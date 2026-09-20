package com.aebel.expensemanager;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

@CapacitorPlugin(
    name = "SaveFile",
    permissions = {
        @Permission(strings = {android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, alias = "storage")
    }
)
public class SaveFilePlugin extends Plugin {

    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @PluginMethod
    public void saveFile(PluginCall call) {
        String fileName = call.getString("fileName");
        String data = call.getString("data");
        String contentType = call.getString("contentType", "application/octet-stream");

        if (fileName == null || fileName.isEmpty() || data == null || data.isEmpty()) {
            call.reject("Invalid file name or data", "ERR_INVALID_ARGUMENT");
            return;
        }

        final byte[] bytes;
        try {
            bytes = Base64.decode(data, Base64.DEFAULT);
        } catch (IllegalArgumentException ex) {
            call.reject("Invalid file data", "ERR_INVALID_DATA");
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveViaMediaStore(fileName, contentType, bytes, call);
        } else {
            if (!hasPermission("storage")) {
                call.setKeepAlive(true);
                requestAllPermissions(call, "storagePermissionCallback");
                return;
            }
            saveLegacy(fileName, contentType, bytes, call);
        }
    }

    @PermissionCallback
    private void storagePermissionCallback(PluginCall call) {
        if (call.isReleased()) {
            return;
        }
        if (hasPermission("storage")) {
            String fileName = call.getString("fileName");
            String contentType = call.getString("contentType", "application/octet-stream");
            String data = call.getString("data");
            if (fileName == null || data == null) {
                call.reject("Invalid file name or data", "ERR_INVALID_ARGUMENT");
                return;
            }
            saveLegacy(fileName, contentType, Base64.decode(data, Base64.DEFAULT), call);
        } else {
            call.reject("Storage permission was denied", "ERR_PERMISSION_DENIED");
        }
    }

    private void saveViaMediaStore(String fileName, String contentType, byte[] bytes, PluginCall call) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                Uri uri = null;
                try {
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
                    values.put(MediaStore.MediaColumns.MIME_TYPE, contentType);
                    values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/");

                    Uri collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
                    ContentResolver resolver = getContext().getContentResolver();
                    uri = resolver.insert(collection, values);
                    if (uri == null) {
                        fail("Could not create the file in the Downloads folder", "ERR_WRITE_FAILED", call);
                        return;
                    }
                    OutputStream out = resolver.openOutputStream(uri);
                    if (out == null) {
                        failAndCleanup(uri, "Could not open the file for writing", "ERR_WRITE_FAILED", call);
                        return;
                    }
                    out.write(bytes);
                    out.flush();
                    out.close();
                    resolve(fileName, call);
                } catch (Exception ex) {
                    failAndCleanup(uri, "Could not save the file: " + ex.getMessage(), "ERR_WRITE_FAILED", call);
                }
            }
        }).start();
    }

    private void saveLegacy(String fileName, String contentType, byte[] bytes, PluginCall call) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                    if (dir != null && !dir.exists()) {
                        dir.mkdirs();
                    }
                    File file = new File(dir, fileName);
                    FileOutputStream out = new FileOutputStream(file);
                    out.write(bytes);
                    out.flush();
                    out.close();

                    if (getContext() != null) {
                        MediaScannerConnection.scanFile(
                            getContext(),
                            new String[]{file.getAbsolutePath()},
                            new String[]{contentType},
                            null
                        );
                    }
                    resolve(fileName, call);
                } catch (Exception ex) {
                    fail("Could not save the file: " + ex.getMessage(), "ERR_WRITE_FAILED", call);
                }
            }
        }).start();
    }

    private void resolve(final String fileName, final PluginCall call) {
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (call.isReleased()) {
                    return;
                }
                JSObject ret = new JSObject();
                ret.put("fileName", fileName);
                call.resolve(ret);
            }
        });
    }

    private void fail(final String message, final String code, final PluginCall call) {
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (call.isReleased()) {
                    return;
                }
                call.reject(message, code);
            }
        });
    }

    private void failAndCleanup(final Uri uri, final String message, final String code, final PluginCall call) {
        if (uri != null) {
            try {
                getContext().getContentResolver().delete(uri, null, null);
            } catch (Exception ignored) {
            }
        }
        fail(message, code, call);
    }
}