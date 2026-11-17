/**
 * Futbolix - Registration Page JavaScript
 */

function togglePassword(id, button) {
    const input = document.getElementById(id);
    if (!input) return;
    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    if (button) {
        button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
    }
}

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("registrationForm");
    if (form) {
        form.addEventListener("submit", function (event) {
            const password = document.getElementById("password");
            const confirmPassword = document.getElementById("confirmPassword");

            if (password && confirmPassword && password.value !== confirmPassword.value) {
                event.preventDefault();
                alert("Passwords do not match. Please re-enter.");
                confirmPassword.focus();
            }
        });
    }
});
