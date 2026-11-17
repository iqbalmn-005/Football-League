/**
 * Futbolix - Login Page JavaScript
 */

function togglePassword() {
    const password = document.getElementById("password");
    if (!password) return;
    const isHidden = password.type === "password";
    password.type = isHidden ? "text" : "password";
    const btn = document.querySelector(".password-toggle");
    if (btn) {
        btn.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
    }
}
