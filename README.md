# cognopolis-client

Официальный Python-клиент игры **Cognopolis** — учебного MMO-полигона курса
«От нуля до своих агентов». Живой мир: https://kindomklaster.com

Этот репозиторий — **публичное зеркало** каталога `client/` основного (приватного)
репозитория движка. Он существует, чтобы клиент ставился анонимно — из Colab/Kaggle,
без git-доступа и учётных данных.

## Установка

Первая ячейка ноутбука (Colab/Kaggle):

```python
%pip install "cognopolis-client @ git+https://github.com/ITrubnikov/Train_of_Thought-Cognopolis-client.git"
```

Вариант быстрее (tar.gz по HTTPS, git не нужен вовсе):

```python
%pip install https://codeload.github.com/ITrubnikov/Train_of_Thought-Cognopolis-client/tar.gz/refs/heads/main
```

## Быстрый старт

```python
from cognopolis_client import Client

# Токен жителя копируется в игре: Ратуша → вкладка «аккаунт» (или экран «Жители»).
with Client("https://kindomklaster.com", token=MY_GAME_TOKEN) as c:
    me = c.get_character()
    print(me["name"], me["hp"], me["position"])
```

Цикл агента — `observe → decide → act → wait`:

```python
with Client("https://kindomklaster.com", token=MY_GAME_TOKEN) as c:
    c.move_dir("south")   # шаг на одну клетку
    c.wait_cooldown()     # выждать кулдаун действия
    c.gather()            # добыть ресурс на клетке
    c.wait_cooldown()
```

Каждое действие возвращает `{result, cooldown, character}`; нарушения правил приходят
как `GameError` со стабильным `.code`. Примеры агентов — в `examples/`.

## Это зеркало — PR сюда не принимаются

Источник истины — каталог `client/` основного репозитория движка Cognopolis.
Изменения попадают в игру через основной репозиторий, а зеркало обновляется скриптом
`tools/sync_from_game_repo.sh` (см. шапку скрипта). Issue по клиенту заводите
в основном проекте курса.
