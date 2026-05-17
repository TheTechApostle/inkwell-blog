# The Inkwell — Flask Blog

A fully functional blog built with Python Flask + Tailwind CSS (CDN).

## Features

- **Public site**: Homepage with featured hero, post grid, pagination
- **Post detail**: Full article view with prose styling, comments, sidebar
- **Category pages**: Browse posts by topic
- **Search**: Full-text search across titles and content
- **About page**: Publication info
- **Admin panel**: Create, edit, delete posts; manage categories
- **Comments**: Readers can comment on posts
- **SQLite database**: Seeded with sample articles on first run

## Stack

- **Backend**: Python / Flask / SQLAlchemy
- **Database**: SQLite (easily swappable to PostgreSQL)
- **Frontend**: Tailwind CSS (CDN), Google Fonts, vanilla JS
- **Fonts**: Playfair Display (display) + DM Sans (body) + DM Mono (labels)

## Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Open http://localhost:5000 in your browser.

## Pages

| URL | Description |
|-----|-------------|
| `/` | Homepage |
| `/post/<slug>` | Article detail |
| `/category/<slug>` | Category listing |
| `/search?q=...` | Search |
| `/about` | About page |
| `/admin` | Admin dashboard |
| `/admin/post/new` | Create post |
| `/admin/post/<id>/edit` | Edit post |
| `/admin/categories` | Manage categories |

## Customization

- **Site name**: Change `"The Inkwell"` in `inject_globals()` in `app.py`
- **Colors**: Edit Tailwind config in `base.html`
- **Categories**: Add/remove via Admin → Categories
- **Secret key**: Set `SECRET_KEY` environment variable in production
- **Database**: Change `SQLALCHEMY_DATABASE_URI` for PostgreSQL

## Production Notes

- Set `SECRET_KEY` to a random string
- Set `DEBUG=False`
- Use gunicorn: `gunicorn -w 4 app:app`
- Switch SQLite → PostgreSQL for multi-user deployments
