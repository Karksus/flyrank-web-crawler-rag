document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const messageDiv = document.getElementById('message');

    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            try {
                const response = await fetch('/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });

                const data = await response.json();
                if (response.ok) {
                    messageDiv.innerHTML = '<p style="color: green;">Registration successful! Redirecting to login...</p>';
                    setTimeout(() => {
                        window.location.href = '/auth/login';
                    }, 1500);
                } else {
                    messageDiv.innerHTML = `<p style="color: red;">${data.detail || 'Registration failed'}</p>`;
                }
            } catch (error) {
                messageDiv.innerHTML = '<p style="color: red;">An error occurred</p>';
            }
        });
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            try {
                const response = await fetch('/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });

                const data = await response.json();
                if (response.ok) {
                    messageDiv.innerHTML = '<p style="color: green;">Login successful! Redirecting...</p>';
                    setTimeout(() => {
                        window.location.href = '/dashboard';
                    }, 1500);
                } else {
                    messageDiv.innerHTML = `<p style="color: red;">${data.detail || 'Login failed'}</p>`;
                }
            } catch (error) {
                messageDiv.innerHTML = '<p style="color: red;">An error occurred</p>';
            }
        });
    }
});
