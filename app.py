from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Admin credentials — set these as environment variables
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'password')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

db = SQLAlchemy(app)

# ─── Models ────────────────────────────────────────────────────────────────────

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    slug = db.Column(db.String(50), nullable=False, unique=True)
    posts = db.relationship('Post', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(400))
    author = db.Column(db.String(100), default='Admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published = db.Column(db.Boolean, default=True)
    featured = db.Column(db.Boolean, default=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')
    read_time = db.Column(db.Integer, default=5)

    def __repr__(self):
        return f'<Post {self.title}>'

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

    def __repr__(self):
        return f'<Comment by {self.name}>'

class PageView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(300), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    ip_hash = db.Column(db.String(64))
    referrer = db.Column(db.String(300))
    user_agent = db.Column(db.String(300))
    country = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

def calc_read_time(content):
    words = len(content.split())
    return max(1, words // 200)

def track_visit(path, post_id=None):
    import hashlib
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
        referrer = request.referrer or ''
        ua = request.headers.get('User-Agent', '')[:300]
        # Skip bots
        bot_keywords = ['bot', 'crawler', 'spider', 'ping', 'monitoring', 'render']
        if any(k in ua.lower() for k in bot_keywords):
            return
        pv = PageView(path=path[:300], post_id=post_id, ip_hash=ip_hash,
                      referrer=referrer[:300], user_agent=ua)
        db.session.add(pv)
        db.session.commit()
    except Exception:
        pass

# ─── Context Processors ────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    categories = Category.query.all()
    recent_posts = Post.query.filter_by(published=True).order_by(Post.created_at.desc()).limit(5).all()
    return dict(categories=categories, recent_posts=recent_posts, site_name="The Inkwell")

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    track_visit('/')
    page = request.args.get('page', 1, type=int)
    featured = Post.query.filter_by(published=True, featured=True).order_by(Post.created_at.desc()).first()
    posts = Post.query.filter_by(published=True).order_by(Post.created_at.desc()).paginate(page=page, per_page=6)
    return render_template('index.html', posts=posts, featured=featured)

@app.route('/post/<slug>')
def post_detail(slug):
    post = Post.query.filter_by(slug=slug, published=True).first_or_404()
    track_visit(f'/post/{slug}', post_id=post.id)
    related = Post.query.filter(
        Post.category_id == post.category_id,
        Post.id != post.id,
        Post.published == True
    ).limit(3).all()
    return render_template('post_detail.html', post=post, related=related)

@app.route('/post/<slug>/comment', methods=['POST'])
def add_comment(slug):
    post = Post.query.filter_by(slug=slug, published=True).first_or_404()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    body = request.form.get('body', '').strip()

    if not name or not email or not body:
        flash('All fields are required.', 'error')
        return redirect(url_for('post_detail', slug=slug))

    comment = Comment(name=name, email=email, body=body, post_id=post.id)
    db.session.add(comment)
    db.session.commit()
    flash('Your comment has been posted!', 'success')
    return redirect(url_for('post_detail', slug=slug) + '#comments')

@app.route('/category/<slug>')
def category(slug):
    cat = Category.query.filter_by(slug=slug).first_or_404()
    track_visit(f'/category/{slug}')
    page = request.args.get('page', 1, type=int)
    posts = Post.query.filter_by(category_id=cat.id, published=True).order_by(Post.created_at.desc()).paginate(page=page, per_page=6)
    return render_template('category.html', category=cat, posts=posts)

@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    posts = []
    if q:
        posts = Post.query.filter(
            Post.published == True,
            (Post.title.ilike(f'%{q}%') | Post.content.ilike(f'%{q}%'))
        ).order_by(Post.created_at.desc()).all()
    return render_template('search.html', posts=posts, query=q)

@app.route('/about')
def about():
    track_visit('/about')
    return render_template('about.html')

# ─── Admin Routes ──────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('admin/index.html', posts=posts)

@app.route('/admin/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    categories = Category.query.all()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        excerpt = request.form.get('excerpt', '').strip()
        author = request.form.get('author', 'Admin').strip()
        cat_id = request.form.get('category_id') or None
        published = 'published' in request.form
        featured = 'featured' in request.form

        if not title or not content:
            flash('Title and content are required.', 'error')
            return render_template('admin/post_form.html', categories=categories)

        slug = slugify(title)
        base_slug = slug
        count = 1
        while Post.query.filter_by(slug=slug).first():
            slug = f'{base_slug}-{count}'
            count += 1

        post = Post(
            title=title, slug=slug, content=content,
            excerpt=excerpt or content[:300] + '...',
            author=author, category_id=cat_id,
            published=published, featured=featured,
            read_time=calc_read_time(content)
        )
        db.session.add(post)
        db.session.commit()
        flash('Post created successfully!', 'success')
        return redirect(url_for('admin'))

    return render_template('admin/post_form.html', categories=categories, post=None)

@app.route('/admin/post/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(id):
    post = Post.query.get_or_404(id)
    categories = Category.query.all()
    if request.method == 'POST':
        post.title = request.form.get('title', '').strip()
        post.content = request.form.get('content', '').strip()
        post.excerpt = request.form.get('excerpt', '').strip()
        post.author = request.form.get('author', 'Admin').strip()
        post.category_id = request.form.get('category_id') or None
        post.published = 'published' in request.form
        post.featured = 'featured' in request.form
        post.updated_at = datetime.utcnow()
        post.read_time = calc_read_time(post.content)
        db.session.commit()
        flash('Post updated!', 'success')
        return redirect(url_for('admin'))
    return render_template('admin/post_form.html', categories=categories, post=post)

@app.route('/admin/post/<int:id>/delete', methods=['POST'])
@login_required
def delete_post(id):
    post = Post.query.get_or_404(id)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            slug = slugify(name)
            if not Category.query.filter_by(slug=slug).first():
                db.session.add(Category(name=name, slug=slug))
                db.session.commit()
                flash(f'Category "{name}" added!', 'success')
            else:
                flash('Category already exists.', 'error')
    categories = Category.query.all()
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/category/<int:id>/delete', methods=['POST'])
@login_required
def delete_category(id):
    cat = Category.query.get_or_404(id)
    db.session.delete(cat)
    db.session.commit()
    flash('Category deleted.', 'success')
    return redirect(url_for('manage_categories'))


# ─── Auth Routes ──────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('logged_in'):
        return redirect(url_for('admin'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('Welcome back!', 'success')
            return redirect(url_for('admin'))
        flash('Incorrect username or password.', 'error')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

# ─── Seed & Init ───────────────────────────────────────────────────────────────

def seed_data():
    if Post.query.first():
        return

    cats = [
        Category(name='Technology', slug='technology'),
        Category(name='Design', slug='design'),
        Category(name='Culture', slug='culture'),
        Category(name='Travel', slug='travel'),
    ]
    db.session.add_all(cats)
    db.session.flush()

    posts_data = [
        {
            'title': 'The Art of Slow Reading in a Fast World',
            'content': '''In an age of infinite scroll and 280-character thoughts, the act of sitting with a book—a real, physical book—feels almost revolutionary. There's a growing movement of people who are deliberately slowing down their reading, not just consuming words but truly inhabiting them.

Slow reading isn't about reading at a snail's pace. It's about reading with presence. It's about letting a sentence land before racing to the next one. It's about pausing when something strikes you, following a tangent into your own memory or imagination, returning enriched.

The neuroscience is fascinating. When we read slowly and deeply, we activate more areas of the brain—not just language processing, but empathy networks, sensory cortices, even motor regions. We're not just decoding symbols; we're living inside another consciousness.

The digital age hasn't killed reading. It's splintered it. We read more words than ever before, but we absorb fewer of them. The solution isn't to reject technology—it's to be intentional about when we use which mode of reading.

Try this: for one week, read one physical book. Leave your phone in another room. Let yourself be bored. Let your mind wander, and then reel it back in. Notice what happens.

The books that changed your life probably didn't do so because you speed-read them. They changed you because they found you at the right moment, and you let them in.''',
            'excerpt': 'In an age of infinite scroll and 280-character thoughts, the act of sitting with a book feels almost revolutionary.',
            'author': 'Elena Marsh',
            'category_id': cats[2].id,
            'featured': True,
            'published': True,
        },
        {
            'title': 'Why Brutalist Web Design is Making a Comeback',
            'content': '''Brutalism in architecture was never meant to be pretty. It was meant to be honest. Raw concrete, exposed structure, function before form. And now, decades after its heyday, a similar philosophy is reshaping the web.

Brutalist web design strips away the polished veneer of modern UI. No smooth gradients. No gentle shadows. No apologetically rounded corners. Instead: bold typography, stark contrast, unmediated grids, and a refusal to hide the bones of the thing.

Why now? Perhaps it's a reaction to sameness. When every SaaS product looks like every other SaaS product—same sans-serif, same blue CTA button, same hero illustration—differentiation demands rupture.

There's something deeply refreshing about a site that doesn't try to seduce you. It presents itself plainly and trusts you to engage on its terms. This is a form of respect.

The best brutalist sites are not accidents. They're the result of designers who know exactly which rules they're breaking and why. The apparent rawness is carefully calibrated. The "ugliness" is a design decision.

Of course, brutalism isn't for every context. A children's hospital shouldn't feel like an avant-garde art gallery. But for cultural institutions, publications, personal portfolios, and forward-thinking brands, it offers something rare: a personality.

The web got very smooth, very fast. Brutalism is the texture returning.''',
            'excerpt': "Brutalism in architecture was never meant to be pretty. It was meant to be honest. And now, it's reshaping the web.",
            'author': 'Jonas Veld',
            'category_id': cats[1].id,
            'published': True,
        },
        {
            'title': 'The Quiet Revolution of Edge Computing',
            'content': '''For most of computing's history, we've been moving data to where the computation happens. Now we're flipping the script: moving computation to where the data is.

Edge computing isn't a new concept, but it's reaching an inflection point. As IoT devices proliferate, as latency becomes a competitive advantage, as privacy regulations tighten—the case for processing data closer to its source has never been stronger.

The classic example is autonomous vehicles. A self-driving car cannot afford the round-trip latency of sending sensor data to a cloud server and waiting for a response. By the time the answer arrives, you're in a ditch. The computation must happen in the car, in milliseconds.

But edge computing's implications extend far beyond cars. Factories where machine vision detects defects without sending footage offsite. Hospitals where patient monitoring happens locally, keeping sensitive data private. Smart cities where traffic systems adjust in real time.

The infrastructure challenge is substantial. You're not managing a handful of data centers anymore—you're managing potentially millions of edge nodes, each of which needs to be updated, secured, and monitored.

But the opportunity is equally substantial. The companies that solve the edge computing infrastructure problem will have enormous leverage in the coming decade.

The cloud isn't going away. But the edge is arriving.''',
            'excerpt': "For most of computing's history, we moved data to computation. Now we're flipping the script.",
            'author': 'Priya Nandan',
            'category_id': cats[0].id,
            'published': True,
        },
        {
            'title': 'Kyoto in November: A Love Letter',
            'content': '''November is the month Kyoto saves itself for. The tourists of cherry blossom season have gone home. The summer heat has broken. And the maples—oh, the maples—have turned themselves into fire.

I arrived on a Tuesday, which is the best day to arrive anywhere you want to yourself. The Philosopher's Path was almost quiet. An old man raked leaves into perfect lines. A cat watched him from a stone wall with the particular disdain cats reserve for effort.

The temples in autumn light do something that photographs cannot capture. The light in late afternoon turns amber and then gold and then something that doesn't have a name in any language I speak. You stop walking. You just stand there.

I ate kaiseki at a restaurant where the chef had been making the same dishes for forty years. Each course arrived like a small argument for patience. The dashi was profound. I don't know what else to say about it.

Fushimi Inari at dawn, before the crowds: the torii gates stretch into the mountain and the mist moves between them and you understand, briefly, why humans invented gods.

I will go back. I always say I'll go back and usually I don't. But Kyoto is different. Kyoto is one of those places that lodges in you, that makes a claim.

Go in November. Go on a Tuesday. Stay longer than you think you need to.''',
            'excerpt': 'November is the month Kyoto saves itself for. The tourists have gone home, and the maples have turned themselves into fire.',
            'author': 'Sarah Okonkwo',
            'category_id': cats[3].id,
            'published': True,
        },
        {
            'title': 'On the Design of Time: Clocks, Calendars, and Cognition',
            'content': '''We tend to think of time as something that exists independently of us—a river we're all floating down. But the tools we use to measure and organize time shape how we experience it in profound ways.

The mechanical clock didn't just tell time. It synchronized labor. Before widespread clock ownership, workers arrived when they arrived. After, lateness became a moral failure. The clock created punctuality as a virtue.

The Gregorian calendar, for all its familiarity, is a political document. Its months are named after Roman emperors and gods. Its week structure is inherited from Babylon via Judaism via Christianity. We organize our lives around an artifact of empire and theology, largely without noticing.

Digital calendars have introduced new temporal pathologies. The meeting that gets accepted because the slot is technically open. The back-to-back blocks that leave no time for thinking. The notification that fractures the present moment with demands from the scheduled future.

Some cultures experience time as cyclical rather than linear. The Maya Long Count Calendar doesn't just measure time—it embeds time within a cosmology. Time is not a neutral container; it's a meaning-making structure.

What would it mean to design time differently? Some companies have experimented with meeting-free days, or no-meeting mornings. Some individuals block time for "thinking" the same way they block time for calls.

The calendar is an interface. Like all interfaces, it can be redesigned. The question is what values you want to encode in it.''',
            'excerpt': "The tools we use to measure and organize time shape how we experience it. The clock didn't just tell time - it synchronized labor.",
            'author': 'Marcus Webb',
            'category_id': cats[1].id,
            'published': True,
        },
        {
            'title': 'Open Source is Eating the AI Stack',
            'content': '''A few years ago, the conventional wisdom was that AI would be winner-take-all. The companies with the most data and the most compute would build moats so deep that no one could challenge them. That story is getting complicated.

The release of LLaMA, and the subsequent explosion of open-source models that built on it, changed the calculus. Suddenly capable models were running on laptops. Fine-tuning was happening on consumer hardware. The moat, it turned out, had a leak.

This doesn't mean the large proprietary labs are irrelevant. Frontier model capabilities still matter enormously, and training those models still requires resources that only a handful of organizations have. But the gap is narrowing faster than most people expected.

The implications for the industry are significant. If capable models become a commodity, value accretes elsewhere: to applications, to data, to distribution, to trust. The picks-and-shovels play in AI might not be the models—it might be the infrastructure, the tooling, the workflow integrations.

For developers, this is a golden age. The variety and capability of available models—both open and closed—means you can choose the right tool for the right job. You're not locked in.

The history of technology suggests that when infrastructure gets commoditized, application-layer innovation accelerates. We may be at that inflection point in AI.

The stack is changing. Pay attention.''',
            'excerpt': 'The conventional wisdom was that AI would be winner-take-all. That story is getting complicated.',
            'author': 'Elena Marsh',
            'category_id': cats[0].id,
            'published': True,
        },
    ]

    for data in posts_data:
        slug = slugify(data['title'])
        post = Post(
            title=data['title'], slug=slug,
            content=data['content'], excerpt=data['excerpt'],
            author=data['author'], category_id=data['category_id'],
            featured=data.get('featured', False),
            published=data['published'],
            read_time=calc_read_time(data['content'])
        )
        db.session.add(post)

    db.session.flush()

    comments_data = [
        Comment(name='Amara Diallo', email='a@example.com', body='This resonated with me deeply. I started a one-book-a-month challenge last year and it genuinely changed my relationship with ideas.', post_id=1),
        Comment(name='Tom K.', email='t@example.com', body="The point about empathy networks is fascinating. Any sources you'd recommend on the neuroscience of reading?", post_id=1),
        Comment(name='Lena Brandt', email='l@example.com', body='Been seeing more brutalist sites lately and honestly I find them refreshing. Tired of everything looking the same.', post_id=2),
    ]
    db.session.add_all(comments_data)
    db.session.commit()

# Always create tables on startup (needed for Render/production)
with app.app_context():
    db.create_all()
    seed_data()

if __name__ == '__main__':
    pass

    import os as _os
    if _os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        try:
            from autoposter import start_scheduler
            start_scheduler(app)
        except Exception as e:
            print(f"[autoposter] Could not start scheduler: {e}")

    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=port)



@app.route('/admin/analytics')
@login_required
def analytics():
    from datetime import timedelta
    from sqlalchemy import func, cast, Date

    today = datetime.utcnow().date()

    # Total stats
    total_views   = PageView.query.count()
    total_posts   = Post.query.filter_by(published=True).count()
    total_comments = Comment.query.count()
    # Unique visitors (by ip_hash, last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    unique_visitors = db.session.query(func.count(func.distinct(PageView.ip_hash)))        .filter(PageView.created_at >= thirty_days_ago).scalar() or 0

    # Views per day for last 30 days
    daily_views = db.session.query(
        func.date(PageView.created_at).label('day'),
        func.count(PageView.id).label('views')
    ).filter(PageView.created_at >= thirty_days_ago)     .group_by(func.date(PageView.created_at))     .order_by(func.date(PageView.created_at)).all()

    # Fill missing days with 0
    daily_map = {str(r.day): r.views for r in daily_views}
    daily_labels = []
    daily_data = []
    for i in range(29, -1, -1):
        day = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        daily_labels.append((today - timedelta(days=i)).strftime('%b %d'))
        daily_data.append(daily_map.get(day, 0))

    # Top posts by views
    top_posts = db.session.query(
        Post.title, Post.slug,
        func.count(PageView.id).label('views')
    ).join(PageView, PageView.post_id == Post.id)     .group_by(Post.id)     .order_by(func.count(PageView.id).desc())     .limit(10).all()

    # Top referrers
    top_referrers = db.session.query(
        PageView.referrer,
        func.count(PageView.id).label('count')
    ).filter(PageView.referrer != '', PageView.referrer != None)     .group_by(PageView.referrer)     .order_by(func.count(PageView.id).desc())     .limit(10).all()

    # Views today
    views_today = PageView.query.filter(
        func.date(PageView.created_at) == today
    ).count()

    # Views this week
    week_ago = datetime.utcnow() - timedelta(days=7)
    views_week = PageView.query.filter(PageView.created_at >= week_ago).count()

    # Recent visitors
    recent_views = PageView.query.order_by(PageView.created_at.desc()).limit(20).all()

    return render_template('admin/analytics.html',
        total_views=total_views,
        total_posts=total_posts,
        total_comments=total_comments,
        unique_visitors=unique_visitors,
        views_today=views_today,
        views_week=views_week,
        daily_labels=daily_labels,
        daily_data=daily_data,
        top_posts=top_posts,
        top_referrers=top_referrers,
        recent_views=recent_views,
    )


@app.route('/sitemap.xml')
def sitemap():
    from flask import Response
    posts = Post.query.filter_by(published=True).order_by(Post.created_at.desc()).all()
    pages = []

    for page in ['index', 'about']:
        pages.append({
            'loc': url_for(page, _external=True),
            'changefreq': 'daily',
            'priority': '1.0' if page == 'index' else '0.5',
        })

    for cat in Category.query.all():
        pages.append({
            'loc': url_for('category', slug=cat.slug, _external=True),
            'changefreq': 'daily',
            'priority': '0.6',
        })

    for post in posts:
        pages.append({
            'loc': url_for('post_detail', slug=post.slug, _external=True),
            'lastmod': post.updated_at.strftime('%Y-%m-%d'),
            'changefreq': 'weekly',
            'priority': '0.9' if post.featured else '0.8',
        })

    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for page in pages:
        xml.append('  <url>')
        xml.append('    <loc>' + page['loc'] + '</loc>')
        if 'lastmod' in page:
            xml.append('    <lastmod>' + page['lastmod'] + '</lastmod>')
        xml.append('    <changefreq>' + page['changefreq'] + '</changefreq>')
        xml.append('    <priority>' + page['priority'] + '</priority>')
        xml.append('  </url>')
    xml.append('</urlset>')

    return Response('\n'.join(xml), mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    from flask import Response
    host = request.host_url.rstrip('/')
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        '',
        'Sitemap: ' + host + '/sitemap.xml',
    ]
    return Response('\n'.join(lines), mimetype='text/plain')


@app.route('/googleabf6ecd49d64f07b.html')
def google_verify():
    from flask import Response
    return Response('google-site-verification: googleabf6ecd49d64f07b.html', mimetype='text/html')

# ─── Auto-poster Admin Routes ─────────────────────────────────────────────────

@app.route('/admin/autoposter')
@login_required
def autoposter_status():
    from autoposter import (
        INTERVAL_HOURS, POSTS_PER_RUN, NEWS_API_KEY,
        GROQ_API_KEY, AI_AUTHOR, NEWS_COUNTRY
    )
    ai_posts = Post.query.filter_by(author=AI_AUTHOR).order_by(Post.created_at.desc()).all()
    config = {
        'interval_hours':    INTERVAL_HOURS,
        'posts_per_run':     POSTS_PER_RUN,
        'news_api_set':      bool(NEWS_API_KEY),
        'groq_api_set': bool(GROQ_API_KEY),
        'news_country':      NEWS_COUNTRY,
        'ai_author':         AI_AUTHOR,
    }
    return render_template('admin/autoposter.html', ai_posts=ai_posts, config=config)

@app.route('/admin/autoposter/run', methods=['POST'])
@login_required
def trigger_autoposter():
    import threading
    from autoposter import run_autoposter
    thread = threading.Thread(target=run_autoposter, args=(app,), daemon=True)
    thread.start()
    flash('Auto-poster triggered! New articles will appear in a few moments.', 'success')
    return redirect(url_for('autoposter_status'))
