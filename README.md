# RustApp

Панель модерации для серверов **Rust**: игроки, чат, баны, проверки, карта и привязка игрового сервера через Oxide.

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/pip-не_нужен-2ea44f" alt="pip не нужен">
  <img src="https://img.shields.io/badge/Oxide-RustApp.cs-ee6b2f" alt="Oxide plugin">
  <img src="https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
</p>

---

## Что внутри

| Модуль | Описание |
| --- | --- |
| Сайт | Интерфейс в стиле rustapp.io |
| API | `server.py` на стандартной библиотеке Python |
| Админка | `/admin.html` — пользователи, проекты, аудит |
| Плагин | `plugin/RustApp.cs` для Oxide |
| База | `data/checkapp.db` (создаётся при запуске) |

---

## Быстрый старт

Нужен **Python 3.10+**. Зависимости через pip ставить не нужно.

```bash
git clone https://github.com/yukkayho/RustApp-full.git
cd RustApp-full
copy .env.example .env
python server.py
```

На Windows, если `python` не находится:

```powershell
copy .env.example .env
py -3 server.py
```

Откройте:

| Страница | URL |
| --- | --- |
| Сайт | http://127.0.0.1:8081/ |
| Админ-панель | http://127.0.0.1:8081/admin.html |
| Регистрация | http://127.0.0.1:8081/client/auth |

Порт по умолчанию `8081`. Смена: `CHECKAPP_PORT` в `.env`.

---

## Админ по умолчанию

| | |
| --- | --- |
| Email | `admin@gmail.com` |
| Пароль | `admin123` |

> Смените пароль, если панель доступна из интернета. Учётка создаётся автоматически при пустой базе.

---

## Плагин на игровой сервер

1. Скопируйте [`plugin/RustApp.cs`](plugin/RustApp.cs) в `oxide/plugins`.
2. В конфиге плагина укажите API URL панели:
   - локально — `http://ВАШ_IP:8081`
   - с доменом — `https://ваш-домен`
3. Перезагрузите плагин:

```bash
oxide.reload RustApp
```

4. На сайте создайте проект, возьмите код привязки и введите его в игре.

---

<details>
<summary><strong>Домен и nginx</strong></summary>

A-запись домена → IP сервера. Пример прокси на Python `:8081`:

```nginx
server {
    listen 80;
    server_name your-domain.ru www.your-domain.ru;
    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

HTTPS:

```bash
certbot --nginx -d your-domain.ru -d www.your-domain.ru
```

В `.env`:

```env
PUBLIC_SITE=https://your-domain.ru
DISCORD_REDIRECT_URI=https://your-domain.ru/auth/discord/callback
```

Если сайт за Cloudflare, SSL ставьте **Full (strict)** — иначе возможен редирект-цикл.

</details>

<details>
<summary><strong>systemd на Linux</strong></summary>

```ini
[Unit]
Description=RustApp
After=network.target

[Service]
WorkingDirectory=/var/www/rustapp
ExecStart=/usr/bin/python3 -u /var/www/rustapp/server.py
Restart=always
Environment=CHECKAPP_PORT=8081

[Install]
WantedBy=multi-user.target
```

</details>

<details>
<summary><strong>База данных</strong></summary>

Файл: `data/checkapp.db`.

Чистый старт: остановите `server.py`, удалите `data/checkapp.db`, запустите снова. Админ `admin@gmail.com` / `admin123` создастся заново.

</details>
