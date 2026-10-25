document.addEventListener('DOMContentLoaded', () => {
    const createBotForm = document.getElementById('createBotForm');
    
    if (createBotForm) {
        createBotForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const url = document.getElementById('url').value;
            
            const btn = createBotForm.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.textContent = 'Creating...';
            
            try {
                const response = await fetch('/companies/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ base_url: url })
                });

                const data = await response.json();
                if (response.ok) {
                    window.location.href = data.redirect || `/companies/${data.company_id}/status`;
                } else {
                    alert(data.detail || 'Error creating bot');
                    btn.disabled = false;
                    btn.textContent = 'Create Bot';
                }
            } catch (error) {
                alert('An error occurred');
                btn.disabled = false;
                btn.textContent = 'Create Bot';
            }
        });
    }
});
