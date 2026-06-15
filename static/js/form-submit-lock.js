(function () {
    "use strict";

    var lockedForms = new Set();

    function submitControls(form) {
        return form.querySelectorAll('button[type="submit"], input[type="submit"], input[type="image"]');
    }

    function rememberControl(control) {
        if (control.dataset.submitLockRemembered === "true") {
            return;
        }
        if (control.tagName === "BUTTON") {
            control.dataset.submitLockOriginalHtml = control.innerHTML;
        }
        if (control.tagName === "INPUT") {
            control.dataset.submitLockOriginalValue = control.value;
        }
        control.dataset.submitLockWasDisabled = control.disabled ? "true" : "false";
        control.dataset.submitLockRemembered = "true";
    }

    function showSubmittingState(control) {
        rememberControl(control);
        control.setAttribute("aria-disabled", "true");
        control.classList.add("submit-lock-pending");

        var text = control.dataset.submittingText || "Processing...";
        if (control.tagName === "BUTTON") {
            control.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> ' + text;
        } else if (control.type !== "image") {
            control.value = text;
        }
    }

    function lockForm(form, submitter) {
        form.dataset.submitLocked = "true";
        lockedForms.add(form);

        var controls = submitControls(form);
        controls.forEach(rememberControl);
        if (submitter) {
            showSubmittingState(submitter);
        }

        // Wait until the browser has captured the clicked submitter's name/value.
        window.setTimeout(function () {
            controls.forEach(function (control) {
                control.disabled = true;
            });
        }, 0);
    }

    function unlockForm(form) {
        delete form.dataset.submitLocked;

        submitControls(form).forEach(function (control) {
            control.disabled = control.dataset.submitLockWasDisabled === "true";
            control.removeAttribute("aria-disabled");
            control.classList.remove("submit-lock-pending");

            if (control.tagName === "BUTTON") {
                control.innerHTML = control.dataset.submitLockOriginalHtml;
            } else if (
                control.tagName === "INPUT" &&
                control.type !== "image"
            ) {
                control.value = control.dataset.submitLockOriginalValue;
            }
        });
    }

    document.addEventListener("click", function (event) {
        var target = event.target;
        var control = target instanceof Element
            ? target.closest('button[type="submit"], input[type="submit"], input[type="image"]')
            : null;
        if (control && control.form && control.form.dataset.submitLocked === "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || form.dataset.submitLock === "off") {
            return;
        }

        if (form.dataset.submitLocked === "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }

        // Existing form handlers may reject custom validation or confirmation.
        window.setTimeout(function () {
            if (!event.defaultPrevented && form.isConnected) {
                lockForm(form, event.submitter);
            }
        }, 0);
    });

    window.addEventListener("pageshow", function () {
        lockedForms.forEach(unlockForm);
        lockedForms.clear();
    });
})();
