let adminCode = null;

document.addEventListener('DOMContentLoaded', () => {
    if (window.vkBridge) {
        vkBridge.send('VKWebAppInit');
    }

    // хэш-роутинг
    const hash = window.location.hash.replace('#', '');
    if (hash === 'admin' || hash === 'admin-panel') {
        setTimeout(() => showSection('admin-panel'), 100);
    } else if (hash === 'add' || hash === 'found') {
        setTimeout(() => showSection('add-item'), 100);
    } else if (hash === 'search' || hash === 'lost') {
        setTimeout(() => showSection('search-item'), 100);
    }

    const addForm = document.getElementById('addForm');
    if (addForm) {
        addForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const btn = addForm.querySelector('.vk-btn-primary');
            const orig = btn.innerHTML;
            btn.innerHTML = 'Отправка...';
            btn.style.opacity = '0.7';

            const name = document.getElementById('itemName').value;
            const cat = document.getElementById('itemCategory').value;
            const place = document.getElementById('itemPlace').value;
            const details = document.getElementById('itemDetails').value;

            fetch('/app/api/items', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: name, category: cat, place: place, details: details, type: 'found' })
            })
            .then(r => r.json())
            .then(() => {
                btn.innerHTML = 'Добавлено!';
                btn.style.background = '#4CAF50';
                btn.style.color = 'white';
                btn.style.opacity = '1';
                setTimeout(() => {
                    showSection('main');
                    addForm.reset();
                    btn.innerHTML = orig;
                    btn.style.background = '';
                    btn.style.color = '';
                }, 2000);
            })
            .catch(() => {
                btn.innerHTML = orig;
                btn.style.opacity = '1';
                alert('Не удалось отправить, попробуйте ещё раз');
            });
        });
    }

    const lostForm = document.getElementById('lostForm');
    if (lostForm) {
        lostForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const btn = lostForm.querySelector('.vk-btn-primary');
            const orig = btn.innerHTML;
            btn.innerHTML = 'Отправка...';
            btn.style.opacity = '0.7';

            const name = document.getElementById('lostName').value;
            const cat = document.getElementById('lostCategory').value;
            const place = document.getElementById('lostPlace').value;
            const details = document.getElementById('lostDetails').value;

            fetch('/app/api/items', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: name, category: cat, place: place, details: details, type: 'lost' })
            })
            .then(r => r.json())
            .then(() => {
                btn.innerHTML = 'Зарегистрировано!';
                btn.style.background = '#4CAF50';
                btn.style.color = 'white';
                btn.style.opacity = '1';
                setTimeout(() => {
                    showSection('main');
                    lostForm.reset();
                    btn.innerHTML = orig;
                    btn.style.background = '';
                    btn.style.color = '';
                }, 2000);
            })
            .catch(() => {
                btn.innerHTML = orig;
                btn.style.opacity = '1';
                alert('Не удалось отправить, попробуйте ещё раз');
            });
        });
    }
});

function showSection(sectionId) {
    if (sectionId === 'admin-panel' && !adminCode) {
        const code = prompt('Введите код администратора:');
        if (!code) return;
        adminCode = code.trim();
    }

    document.getElementById('main-section').classList.add('hidden');
    document.getElementById('add-item').classList.add('hidden');
    document.getElementById('search-item').classList.add('hidden');
    document.getElementById('admin-panel').classList.add('hidden');

    if (sectionId === 'main') {
        document.getElementById('main-section').classList.remove('hidden');
    } else {
        document.getElementById(sectionId).classList.remove('hidden');
    }
}

function adminFetch(url, options = {}) {
    options.headers = Object.assign({}, options.headers, { 'X-Admin-Code': adminCode || '' });
    return fetch(url, options).then(r => {
        if (r.status === 403) {
            adminCode = null;
            throw new Error('forbidden');
        }
        return r.json();
    });
}

function adminAction(actionType) {
    const results = document.getElementById('adminResults');
    results.style.display = 'block';
    results.innerHTML = '<span style="color: var(--vk-text-muted);">Загрузка...</span>';

    if (actionType === 'stats') {
        adminFetch('/app/api/admin/stats')
            .then(data => { results.innerHTML = data.text; })
            .catch(() => { results.innerHTML = 'Ошибка доступа. Введите код ещё раз.'; });

    } else if (actionType === 'recent') {
        adminFetch('/app/api/admin/recent')
            .then(data => { results.innerHTML = data.text; })
            .catch(() => { results.innerHTML = 'Ошибка доступа. Введите код ещё раз.'; });

    } else if (actionType === 'list_admins') {
        adminFetch('/app/api/admin/list')
            .then(data => { results.innerHTML = data.text; })
            .catch(() => { results.innerHTML = 'Ошибка доступа. Введите код ещё раз.'; });

    } else if (actionType === 'gen_code') {
        adminFetch('/app/api/admin/gencode', { method: 'POST' })
            .then(data => {
                results.innerHTML = `<b>Новый код доступа:</b><br><code style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 6px; display: inline-block; margin-top: 8px;">${data.code}</code>`;
            })
            .catch(() => { results.innerHTML = 'Ошибка доступа. Введите код ещё раз.'; });

    } else if (actionType === 'revoke_admin') {
        results.innerHTML = 'Снять права можно командой боту: /admin revoke [user_id]';

    } else if (actionType === 'clear_db') {
        const typed = prompt('Это НЕОБРАТИМО удалит все находки и потери. Введите слово УДАЛИТЬ для подтверждения:');
        if (typed !== 'УДАЛИТЬ') {
            results.innerHTML = 'Отменено.';
            return;
        }
        results.innerHTML = '<span style="color: var(--vk-text-muted);">Удаление...</span>';
        adminFetch('/app/api/admin/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm: typed })
        })
            .then(data => { results.innerHTML = data.text; })
            .catch(() => { results.innerHTML = 'Ошибка доступа. Введите код ещё раз.'; });
    }
}

function performSearch() {
    const input = document.getElementById('searchInput');
    const results = document.getElementById('searchResults');
    const btn = document.querySelector('#search-item .vk-btn-primary');

    if (!input.value.trim()) return;

    const orig = btn.innerHTML;
    btn.innerHTML = 'Поиск...';
    btn.style.opacity = '0.7';
    results.style.display = 'none';

    fetch('/app/api/search?q=' + encodeURIComponent(input.value.trim()))
        .then(r => r.json())
        .then(data => {
            btn.innerHTML = orig;
            btn.style.opacity = '1';
            results.style.display = 'block';

            if (!data.items || data.items.length === 0) {
                results.innerHTML = '<p style="text-align:center; color: var(--vk-text-muted);">Похожих вещей пока нет. Если кто-то сдаст — придёт уведомление в бот.</p>';
                return;
            }

            let html = '<div class="sferum-list">';
            data.items.forEach(item => {
                html += `
                    <div class="sferum-list-item" style="cursor: default;">
                        <div class="item-icon" style="background: rgba(255,255,255,0.1); font-size: 20px;">📦</div>
                        <div class="item-text">
                            <div class="item-title">${item.title}</div>
                            <div class="item-subtitle">Место: ${item.place}</div>
                        </div>
                    </div>`;
            });
            html += '</div>';
            results.innerHTML = html;
        })
        .catch(() => {
            btn.innerHTML = orig;
            btn.style.opacity = '1';
            results.style.display = 'block';
            results.innerHTML = '<p style="text-align:center; color: var(--vk-text-muted);">Не удалось загрузить результаты</p>';
        });
}
