// Telegram WebApp объект
const tg = window.Telegram.WebApp;

// Состояние приложения
let state = {
    user: null,
    departments: [],
    groups: [],
    currentData: [],
    selectedDepartment: null,
    selectedGroup: null
};

// Инициализация
tg.ready();
tg.expand(); // Разворачиваем на весь экран
tg.MainButton.hide(); // Прячем кнопку по умолчанию

// Получаем initData и отправляем на сервер для валидации
const initData = tg.initData;

async function initialize() {
    try {
        console.log("Initializing with initData:", initData ? "present" : "missing");
        
        const response = await fetch('/api/me', {
            headers: {
                'Authorization': `tg ${initData || 'test'}`
            }
        });
        
        if (!response.ok) {
            console.warn('Auth failed, but continuing with test data');
            // Продолжаем с тестовыми данными
            state.user = {
                id: 123456789,
                first_name: "Test",
                last_name: "User"
            };
        } else {
            state.user = await response.json();
        }
        
        // Показываем информацию о пользователе
        document.getElementById('user-info').textContent = 
            `👤 ${state.user.first_name} ${state.user.last_name || ''}`.trim();
        
        // Загружаем отделения
        await loadDepartments();
        
    } catch (error) {
        console.error('Initialization error:', error);
        // Всё равно пробуем загрузить данные
        state.user = { id: 1, first_name: "Test", last_name: "User" };
        document.getElementById('user-info').textContent = '👤 Test User';
        await loadDepartments();
    }
}

async function loadDepartments() {
    try {
        const response = await fetch('/api/departments', {
            headers: {
                'Authorization': `tg ${initData}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load departments');
        
        state.departments = await response.json();
        renderDepartments();
        
    } catch (error) {
        console.error('Error loading departments:', error);
        tg.showAlert('Не удалось загрузить отделения');
    }
}

function renderDepartments() {
    const container = document.getElementById('departments-list');
    
    if (state.departments.length === 0) {
        container.innerHTML = '<div class="empty-state">Нет отделений</div>';
        return;
    }
    
    container.innerHTML = state.departments.map(dept => `
        <div class="card" onclick="selectDepartment(${dept.id})">
            <h3>🏢 ${dept.name}</h3>
        </div>
    `).join('');
    
    // Показываем нужный экран
    showView('departments-view');
}

async function selectDepartment(deptId) {
    state.selectedDepartment = deptId;
    
    try {
        const response = await fetch(`/api/groups/${deptId}`, {
            headers: {
                'Authorization': `tg ${initData}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load groups');
        
        state.groups = await response.json();
        
        const dept = state.departments.find(d => d.id === deptId);
        document.getElementById('department-title').textContent = 
            `👥 Группы: ${dept ? dept.name : ''}`;
        
        renderGroups();
        
    } catch (error) {
        console.error('Error loading groups:', error);
        tg.showAlert('Не удалось загрузить группы');
    }
}

function renderGroups() {
    const container = document.getElementById('groups-list');
    
    if (state.groups.length === 0) {
        container.innerHTML = '<div class="empty-state">Нет групп в этом отделении</div>';
        return;
    }
    
    container.innerHTML = state.groups.map(group => `
        <div class="card" onclick="selectGroup(${group.id})">
            <h3>👤 ${group.cipher}</h3>
            <p>${group.department_name}</p>
        </div>
    `).join('');
    
    showView('groups-view');
}

async function selectGroup(groupId) {
    state.selectedGroup = groupId;
    
    try {
        const response = await fetch(`/api/data/${groupId}`, {
            headers: {
                'Authorization': `tg ${initData}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load data');
        
        state.currentData = await response.json();
        
        const group = state.groups.find(g => g.id === groupId);
        document.getElementById('group-title').textContent = 
            `📊 Данные: ${group ? group.cipher : ''}`;
        
        renderData();
        
    } catch (error) {
        console.error('Error loading data:', error);
        tg.showAlert('Не удалось загрузить данные');
    }
}

function renderData() {
    const tbody = document.getElementById('data-body');
    
    if (state.currentData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="2" class="empty-state">Нет данных</td></tr>';
    } else {
        tbody.innerHTML = state.currentData.map(item => `
            <tr>
                <td>📅 ${item.date}</td>
                <td>👤 ${item.count} чел.</td>
            </tr>
        `).join('');
    }
    
    showView('data-view');
}

function showView(viewId) {
    // Скрываем все view
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });
    
    // Показываем нужный
    document.getElementById(viewId).classList.add('active');
}

function backToDepartments() {
    showView('departments-view');
}

function backToGroups() {
    showView('groups-view');
}

function showAddForm() {
    // Устанавливаем сегодняшнюю дату по умолчанию
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('add-date').value = today;
    document.getElementById('add-count').value = '';
    
    showView('add-view');
}

function cancelAdd() {
    showView('data-view');
}

async function saveData(event) {
    event.preventDefault();
    
    const date = document.getElementById('add-date').value;
    const count = document.getElementById('add-count').value;
    
    if (!date || !count) {
        tg.showAlert('Заполните все поля');
        return;
    }
    
    try {
        const response = await fetch('/api/add', {
            method: 'POST',
            headers: {
                'Authorization': `tg ${initData}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_id: state.selectedGroup,
                date: date,
                count: parseInt(count)
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save');
        }
        
        tg.showAlert('✅ Данные сохранены');
        
        // Обновляем данные
        await selectGroup(state.selectedGroup);
        
    } catch (error) {
        console.error('Error saving data:', error);
        tg.showAlert('❌ Ошибка при сохранении: ' + error.message);
    }
}

// Запускаем при загрузке
initialize();