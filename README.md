# jdupes-web

Веб-интерфейс для ручного рекурсивного запуска `jdupes` по корню примонтированного volume.

## Запуск

```bash
mkdir -p data
docker compose up -d --build
```

Откройте `http://127.0.0.1:8080`. Сканируемый каталог — корень `/data/scan` внутри контейнера, по умолчанию локальный `./data`.

Запуск `jdupes` при старте контейнера **не выполняется**. Задание начинается только кнопкой в UI. Режим выбирается в UI:

- **Поиск дублей** — безопасный режим без удаления;
- **Удаление дублей** — требует отдельного подтверждения в браузере.

Интерфейс показывает статус, progress bar, общее число файлов и обработанное число. Подробный лог и имена файлов не показываются. Одновременно выполняется максимум одно задание.

## Конфигурация

```bash
JDUPES_PORT=8080 SCAN_VOLUME=/srv/files docker compose up -d
```

Для публикации локально собранного образа:

```bash
JDUPES_IMAGE=your-dockerhub-user/jdupes-web:latest docker compose build
```

## Разработка и тесты

```bash
python3 -m unittest discover -s tests -v
python3 app.py
```

## GitHub Actions и Docker Registry

Workflow `.github/workflows/docker.yml` запускает тесты перед сборкой. Pull request только проверяет сборку, а push в `main`, version tags `v*.*.*` и ручной запуск публикуют образ в Docker Hub с тегами `latest`, tag и commit SHA.

В настройках GitHub repository secrets должны быть заданы:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

Значения секретов не входят в репозиторий. Для публикации PAT должен иметь право push в Docker Hub repository `jdupes-web`.

## Ограничения

Точный общий счётчик файлов вычисляется отдельной рекурсивной фазой до запуска `jdupes`, поэтому на больших деревьях UI сначала показывает состояние «Подсчёт файлов». `jdupes` сам формирует результат; его stdout не сохраняется и не отображается.
