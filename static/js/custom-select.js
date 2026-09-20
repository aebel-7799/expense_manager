(function () {
    'use strict';

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function currentLabel(select) {
        if (select.selectedIndex > -1 && select.options[select.selectedIndex]) {
            return select.options[select.selectedIndex].text;
        }
        return select.options.length ? select.options[0].text : '';
    }

    function dispatchChange(select) {
        var event;
        try {
            event = new Event('change', { bubbles: true });
        } catch (e) {
            event = document.createEvent('Event');
            event.initEvent('change', true, true);
        }
        select.dispatchEvent(event);
    }

    function initCustomSelect(select) {
        if (select.getAttribute('data-custom-ready')) return;
        select.setAttribute('data-custom-ready', '1');

        var title = select.getAttribute('data-picker-title') || 'Select an option';

        var trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'custom-select-trigger';
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.textContent = currentLabel(select);
        select.parentNode.insertBefore(trigger, select.nextSibling);

        var overlay = document.createElement('div');
        overlay.className = 'modal-overlay picker-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML =
            '<div class="modal-card-custom picker-card">' +
                '<h3>' + escapeHtml(title) + '</h3>' +
                '<div class="picker-option-list" role="listbox"></div>' +
                '<div class="modal-buttons" style="margin-top: 18px;">' +
                    '<button type="button" class="modal-btn-cancel picker-cancel">Cancel</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        var list = overlay.querySelector('.picker-option-list');
        var cancelBtn = overlay.querySelector('.picker-cancel');
        var options = Array.prototype.slice.call(select.options);
        var buttons = [];

        options.forEach(function (option) {
            if (!option.value) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'picker-option';
            btn.setAttribute('role', 'option');
            btn.textContent = option.text;
            btn.setAttribute('data-value', option.value);
            btn.addEventListener('click', function () {
                select.value = option.value;
                trigger.textContent = option.text;
                highlightSelected();
                closePicker();
                dispatchChange(select);
            });
            list.appendChild(btn);
            buttons.push(btn);
        });

        function highlightSelected() {
            buttons.forEach(function (btn) {
                btn.classList.toggle('selected', btn.getAttribute('data-value') === select.value);
            });
        }

        function openPicker() {
            highlightSelected();
            overlay.style.display = 'flex';
            setTimeout(function () { overlay.classList.add('active'); }, 10);
        }

        function closePicker() {
            overlay.classList.remove('active');
            setTimeout(function () { overlay.style.display = 'none'; }, 250);
        }

        trigger.addEventListener('click', openPicker);
        cancelBtn.addEventListener('click', closePicker);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closePicker();
        });

        // Preserve desktop "required" behaviour when the native select is hidden.
        var form = select.closest('form');
        if (form && select.required) {
            form.addEventListener('submit', function (e) {
                if (!select.value) {
                    e.preventDefault();
                    e.stopPropagation();
                    openPicker();
                }
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var selects = document.querySelectorAll('select.custom-select');
        for (var i = 0; i < selects.length; i++) {
            initCustomSelect(selects[i]);
        }
    });
})();