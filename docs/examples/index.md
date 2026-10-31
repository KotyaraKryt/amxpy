# Примеры

Готовые плагины из папки `examples/plugins` репозитория. Каждый проходит проверку amxpyc и
flake8, и у каждого есть тесты на FakeServer — код на этих страницах вставляется из тех же
файлов.

<div class="ax-cards" markdown>
<a class="ax-card" href="hello/"><em>hello.py</em><b>Привет и /hp</b><span>Приветствие с задержкой, команда, лечение админом, запрет урона по своим</span></a>
<a class="ax-card" href="no-awp/"><em>no_awp.py</em><b>Запрет AWP</b><span>Отмена покупки до списания денег, исключение для админов</span></a>
<a class="ax-card" href="round-mvp/"><em>round_mvp.py</em><b>MVP раунда</b><span>Статистика за раунд, крупный HUD и денежный бонус</span></a>
<a class="ax-card" href="welcome-back/"><em>welcome_back.py</em><b>С возвращением</b><span>Визиты игроков в SQLite по SteamID</span></a>
<a class="ax-card" href="ui-demo/"><em>ui_demo.py</em><b>Меню и HUD</b><span>Меню со страницами, HUD, DHUD, голосование через Menu.ask</span></a>
<a class="ax-card" href="vip/"><em>vip/</em><b>VIP-система</b><span>Плагин-пакет: нативы и форвард для Pawn, SQLite, переводы, PlayerState</span></a>
</div>

Поставить пример на свой сервер — скопируйте файл в `plugins/` проекта и выполните
`amxpy deploy`.
