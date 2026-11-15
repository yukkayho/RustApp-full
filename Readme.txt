RustApp — установка
===================

Требования
----------
- Windows / Linux / macOS
- Python 3.10 или новее (стандартная библиотека, pip не нужен)
- Для игрового сервера: Oxide (uMod) и плагин plugin\RustApp.cs


1. Локальный запуск
-------------------
1. Скопируйте .env.example в .env (если файла .env ещё нет).
2. В папке проекта выполните:

   python server.py

   На Windows можно: py -3 server.py

3. Откройте в браузере:
   Сайт:        http://127.0.0.1:8081/
   Админ-панель: http://127.0.0.1:8081/admin.html

Вход в админку (платформа)
--------------------------
Email:    admin@gmail.com
Пароль:   admin123

Смените пароль после первого входа, если панель выкладываете в интернет.

Обычные пользователи регистрируются на /client/auth.


2. Плагин на игровой сервер
---------------------------
1. Скопируйте plugin\RustApp.cs в oxide/plugins на сервере Rust.
2. В конфиге плагина укажите API URL этого сайта:
   - локально:  http://ВАШ_IP:8081
   - с доменом: https://ваш-домен
3. Перезагрузите плагин: oxide.reload RustApp
4. На сайте создайте проект, получите код привязки сервера и введите его в игре.


3. Домен и nginx (необязательно)
--------------------------------
Привяжите A-запись домена на IP сервера.

Пример nginx (прокси на Python :8081):

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

HTTPS: certbot --nginx -d your-domain.ru -d www.your-domain.ru

В .env задайте:
  PUBLIC_SITE=https://your-domain.ru
  DISCORD_REDIRECT_URI=https://your-domain.ru/auth/discord/callback

Если сайт за Cloudflare, SSL лучше Full (strict), иначе возможен редирект-цикл.


4. systemd (Linux)
------------------
Рабочая папка — каталог с server.py. Пример unit:

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


5. База данных
--------------
SQLite: data\checkapp.db
Чтобы начать с чистой базы — остановите server.py и удалите data\checkapp.db.
При следующем запуске админ admin@gmail.com / admin123 создастся автоматически.


Порт
----
По умолчанию 8081. Можно сменить: CHECKAPP_PORT=8081 в .env или переменной окружения.
