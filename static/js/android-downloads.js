/**
 * Android (Capacitor) download handling for the Downloads page.
 * On the website this file is inert: <a> links keep their normal behaviour.
 * Inside the Capacitor Android app, PDF/CSV downloads are saved directly to the
 * phone's public Downloads folder via the native SaveFilePlugin, so they appear
 * in Files -> Downloads.
 */
(function () {
    'use strict';

    function isAndroidNative() {
        return typeof window !== 'undefined' &&
            typeof Capacitor !== 'undefined' &&
            Capacitor &&
            typeof Capacitor.isNativePlatform === 'function' &&
            Capacitor.isNativePlatform() &&
            typeof Capacitor.getPlatform === 'function' &&
            Capacitor.getPlatform() === 'android';
    }

    function arrayBufferToBase64(buffer) {
        var binary = '';
        var bytes = new Uint8Array(buffer);
        var chunkSize = 0x8000;
        for (var i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        return window.btoa(binary);
    }

    function buildFileName(href, ext) {
        var queryIdx = href.indexOf('?');
        var params = new URLSearchParams(queryIdx >= 0 ? href.slice(queryIdx + 1) : '');
        var type = params.get('type') || 'monthly';
        var date = params.get('date') || '';
        var month = params.get('month') || '';
        var targetVal = (type === 'daily' ? date : month) || 'report';
        return 'report_' + type + '_' + targetVal + '.' + ext;
    }

    function showToast(message, type) {
        var container = document.getElementById('toastContainer');
        if (!container) {
            return;
        }
        var toast = document.createElement('div');
        toast.className = 'toast ' + (type || 'success');
        toast.style.position = 'relative';
        toast.innerHTML = '<span class="toast-icon"></span><span>' + message + '</span><div class="toast-progress"></div>';
        container.appendChild(toast);
        setTimeout(function () {
            toast.classList.add('hiding');
            setTimeout(function () { toast.remove(); }, 300);
        }, 3000);
    }

    function downloadAsFile(anchor, ext, contentType, successMsg) {
        fetch(anchor.href, { credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Request failed with status ' + response.status);
                }
                return response.arrayBuffer();
            })
            .then(function (buffer) {
                var fileName = buildFileName(anchor.href, ext);
                var data = arrayBufferToBase64(buffer);
                return Capacitor.Plugins.SaveFile.saveFile({
                    fileName: fileName,
                    data: data,
                    contentType: contentType
                });
            })
            .then(function () {
                showToast(successMsg, 'success');
            })
            .catch(function () {
                showToast('Download failed. Please try again.', 'error');
            });
    }

    if (!isAndroidNative()) {
        return;
    }

    Capacitor.registerPlugin('SaveFile');

    document.addEventListener('DOMContentLoaded', function () {
        var pdfLinks = document.querySelectorAll('a[href*="/downloads/pdf"]');
        var csvLinks = document.querySelectorAll('a[href*="/downloads/csv"]');

        for (var i = 0; i < pdfLinks.length; i++) {
            pdfLinks[i].addEventListener('click', function (event) {
                event.preventDefault();
                var anchor = this;
                downloadAsFile(anchor, 'pdf', 'application/pdf', 'PDF downloaded successfully');
            });
        }
        for (var j = 0; j < csvLinks.length; j++) {
            csvLinks[j].addEventListener('click', function (event) {
                event.preventDefault();
                var anchor = this;
                downloadAsFile(anchor, 'csv', 'text/csv', 'CSV downloaded successfully');
            });
        }
    });
})();