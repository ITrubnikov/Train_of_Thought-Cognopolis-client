#!/usr/bin/env bash
# Обновить это публичное зеркало из приватного game-репо (каталог client/).
#
# Запускает владелец обоих репо (нужен доступ к приватному движку):
#
#   git clone git@github.com:ITrubnikov/Train_of_Thought-Cognopolis-client.git
#   cd Train_of_Thought-Cognopolis-client
#   tools/sync_from_game_repo.sh <путь-к-Train_of_Thought-Cognopolis>
#   git add -A && git commit   # сообщение подсказывает скрипт
#   git push                   # push в main публичного зеркала (НЕ движка)
#
# Корень зеркала = байт-в-байт client/* движка; файлы самого зеркала
# (README.md, LICENSE, .gitignore, tools/) синк переживают.
set -euo pipefail

GAME_REPO="${1:?usage: tools/sync_from_game_repo.sh <path-to-Train_of_Thought-Cognopolis>}"
SRC="$GAME_REPO/client"
MIRROR="$(cd "$(dirname "$0")/.." && pwd)"

[ -f "$SRC/pyproject.toml" ] || { echo "ERROR: $SRC/pyproject.toml не найден — это точно game-репо?" >&2; exit 1; }
grep -q 'name = "cognopolis-client"' "$SRC/pyproject.toml" \
  || { echo "ERROR: $SRC/pyproject.toml не объявляет пакет cognopolis-client" >&2; exit 1; }

rsync -a --delete \
  --exclude ".git" \
  --exclude "README.md" \
  --exclude "LICENSE" \
  --exclude ".gitignore" \
  --exclude "tools" \
  --exclude "__pycache__" \
  --exclude "*.egg-info" \
  --exclude ".venv" \
  "$SRC/" "$MIRROR/"

SHA="$(git -C "$GAME_REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "Синк client/ → зеркало готов (источник: движок @ $SHA)."
echo "Изменения:"
git -C "$MIRROR" status --short || true
echo
echo "Дальше: git add -A && git commit -m \"sync: client/ @ $SHA\" && git push"
