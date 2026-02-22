# Ветвление в Telegrab

## Структура веток

### `main` — Основная ветка
- **Назначение**: Исходный код приложения
- **Стабильность**: Production-ready
- **Развёртывание**: Серверы пользователей

### `gh-pages` — Документация
- **Назначение**: GitHub Pages сайт с документацией
- **Содержимое**: README.md, документация
- **URL**: https://jebance.github.io/telegrab/

---

## Настройка по умолчанию

### Смена основной ветки на GitHub

1. Перейдите в **Settings** репозитория
2. Найдите раздел **Default branch**
3. Выберите `main` из списка
4. Нажмите **Update**

### Включение GitHub Pages

1. Перейдите в **Settings** → **Pages**
2. В разделе **Build and deployment**:
   - **Source**: Deploy from a branch
   - **Branch**: `gh-pages` / (root)
3. Нажмите **Save**

---

## Рабочий процесс

### Внесение изменений в код

```bash
# Работа в основной ветке
git checkout main
git checkout -b feature/new-feature

# Внесение изменений...
git add .
git commit -m "feat: новая функция"
git push origin feature/new-feature

# Создание Pull Request на GitHub
```

### Обновление документации

```bash
# Документация обновляется автоматически через GitHub Actions
# при пуше в ветку main

# Или вручную:
git checkout gh-pages
git checkout main -- README.md
git commit -m "docs: обновление README"
git push origin gh-pages
```

---

## GitHub Actions

### Автоматическое развёртывание документации

При пуше в `main`:
1. Запускается workflow `.github/workflows/deploy-docs.yml`
2. README.md и документация копируются в `gh-pages`
3. GitHub Pages автоматически обновляется

---

## Защита веток (рекомендуется)

### Для `main`:

1. Settings → **Branches** → **Add branch protection rule**
2. Branch name pattern: `main`
3. Включите:
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging

### Для `gh-pages`:

Защита не требуется, ветка обновляется автоматически.

---

## История

- **До v4.0**: Проект использовал только `gh-pages` для кода
- **v4.0+**: Разделение на `main` (код) и `gh-pages` (документация)
