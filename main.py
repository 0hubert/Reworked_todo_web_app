from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import markdown
import re
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from xml.etree import ElementTree as etree
from sqlalchemy import or_
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///todos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
db = SQLAlchemy(app)

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'md'}

# Custom Markdown Extension for Wiki Links
class WikiLinkProcessor(InlineProcessor):
    def __init__(self, pattern, md):
        super().__init__(pattern, md)
        
    def handleMatch(self, m, data):
        title = m.group(1)
        note = Note.query.filter_by(title=title).first()
        
        el = etree.Element('a')
        if note:
            el.set('href', url_for('view_note', id=note.id))
            el.set('class', 'wiki-link')
        else:
            el.set('href', url_for('new_note', title=title))
            el.set('class', 'wiki-link missing')
        el.text = title
        
        return el, m.start(0), m.end(0)

class WikiLinkExtension(Extension):
    def extendMarkdown(self, md):
        WIKILINK_RE = r'\[\[([\w\s-]+)\]\]'
        wiki_link_pattern = WikiLinkProcessor(WIKILINK_RE, md)
        md.inlinePatterns.register(wiki_link_pattern, 'wikilink', 175)

# Database Model
class FileAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    note_id = db.Column(db.Integer, db.ForeignKey('note.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_size = db.Column(db.Integer)  # Size in bytes
    file_type = db.Column(db.String(50))

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, unique=True)  # Make title unique
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = db.Column(db.String(200))  # Store tags as comma-separated strings
    attachments = db.relationship('FileAttachment', backref='note', lazy=True, cascade="all, delete-orphan")

    def get_linked_notes(self):
        """Find all notes that this note links to"""
        pattern = r'\[\[([\w\s-]+)\]\]'
        matches = re.findall(pattern, self.content)
        return Note.query.filter(Note.title.in_(matches)).all()

    def get_backlinks(self):
        """Find all notes that link to this note"""
        pattern = f'\\[\\[{self.title}\\]\\]'
        linking_notes = Note.query.filter(Note.content.op('REGEXP')(pattern)).all()
        return linking_notes

# Routes
def get_all_notes():
    return Note.query.order_by(Note.updated_at.desc()).all()

@app.route('/')
def index():
    return render_template('index.html', all_notes=get_all_notes())

@app.route('/note/new', methods=['GET', 'POST'])
@app.route('/note/new/<title>', methods=['GET', 'POST'])
def new_note(title=None):
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form['tags']
        
        note = Note(title=title, content=content, tags=tags)
        db.session.add(note)
        
        # Handle file uploads
        files = request.files.getlist('files')
        for file in files:
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                # Create unique filename
                filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{original_filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Create file attachment record
                attachment = FileAttachment(
                    filename=filename,
                    original_filename=original_filename,
                    note=note,
                    file_size=os.path.getsize(file_path),
                    file_type=file.content_type
                )
                db.session.add(attachment)
        
        try:
            db.session.commit()
            return redirect(url_for('view_note', id=note.id))
        except:
            db.session.rollback()
            return "Error: Title must be unique", 400
    
    return render_template('new_note.html', 
                         suggested_title=title,
                         all_notes=get_all_notes())

@app.route('/note/<int:id>')
def view_note(id):
    note = Note.query.get_or_404(id)
    md = markdown.Markdown(extensions=[WikiLinkExtension(), 'fenced_code', 'tables'])
    html_content = md.convert(note.content)
    linked_notes = note.get_linked_notes()
    backlinks = note.get_backlinks()
    
    return render_template('view_note.html', 
                         note=note, 
                         html_content=html_content,
                         linked_notes=linked_notes,
                         backlinks=backlinks,
                         all_notes=get_all_notes(),
                         current_note=note)

@app.route('/note/<int:id>/edit', methods=['GET', 'POST'])
def edit_note(id):
    note = Note.query.get_or_404(id)
    
    if request.method == 'POST':
        note.title = request.form['title']
        note.content = request.form['content']
        note.tags = request.form['tags']
        note.updated_at = datetime.utcnow()
        
        # Handle file uploads
        files = request.files.getlist('files')
        for file in files:
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                # Create unique filename
                filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{original_filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Create file attachment record
                attachment = FileAttachment(
                    filename=filename,
                    original_filename=original_filename,
                    note=note,
                    file_size=os.path.getsize(file_path),
                    file_type=file.content_type
                )
                db.session.add(attachment)
        
        try:
            db.session.commit()
            return redirect(url_for('view_note', id=note.id))
        except:
            db.session.rollback()
            return "Error: Title must be unique", 400
    
    return render_template('edit_note.html', 
                         note=note,
                         all_notes=get_all_notes())

@app.route('/note/<int:id>/delete')
def delete_note(id):
    note = Note.query.get_or_404(id)
    db.session.delete(note)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))

    # Search in titles, content, and tags
    notes = Note.query.filter(
        or_(
            Note.title.ilike(f'%{query}%'),
            Note.content.ilike(f'%{query}%'),
            Note.tags.ilike(f'%{query}%')
        )
    ).all()

    results = []
    for note in notes:
        result = {'note': note, 'matches': []}
        
        # Find matches in content
        content_lines = note.content.split('\n')
        for line in content_lines:
            if query.lower() in line.lower():
                # Get surrounding context (clean up markdown and highlight match)
                cleaned_line = re.sub(r'\[\[(.*?)\]\]', r'\1', line)  # Remove wiki link syntax
                match_start = cleaned_line.lower().find(query.lower())
                if match_start >= 0:
                    start = max(0, match_start - 40)
                    end = min(len(cleaned_line), match_start + len(query) + 40)
                    context = cleaned_line[start:end]
                    # Use re.sub instead of str.replace for case-insensitive replacement
                    highlighted = re.sub(
                        f'({re.escape(query)})',
                        r'<span class="highlight">\1</span>',
                        context,
                        flags=re.IGNORECASE
                    )
                    result['matches'].append(highlighted)

        results.append(result)

    return render_template('search.html', 
                         query=query,
                         results=results,
                         all_notes=get_all_notes())

@app.route('/uploads/<file_id>')
def download_file(file_id):
    attachment = FileAttachment.query.get_or_404(file_id)
    return send_from_directory(app.config['UPLOAD_FOLDER'], attachment.filename)

@app.route('/attachment/<file_id>/delete')
def delete_attachment(file_id):
    attachment = FileAttachment.query.get_or_404(file_id)
    note_id = attachment.note_id
    
    # Delete the actual file
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], attachment.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    # Delete the database record
    db.session.delete(attachment)
    db.session.commit()
    
    return redirect(url_for('view_note', id=note_id))

@app.route('/graph')
def graph_view():
    return render_template('graph.html',
                         all_notes=get_all_notes())

@app.route('/api/graph-data')
def graph_data():
    nodes = []
    edges = []
    node_ids = {}  # To keep track of node indices
    
    # Get all notes and create nodes
    notes = Note.query.all()
    for i, note in enumerate(notes):
        # Add file attachments information
        attachments = [
            {
                'filename': att.original_filename,
                'size': f"{(att.file_size / 1024):.1f} KB"
            } for att in note.attachments
        ]
        
        nodes.append({
            'id': i,
            'title': note.title,
            'tags': note.tags or '',
            'url': url_for('view_note', id=note.id),
            'attachments': attachments  # Add attachments to node data
        })
        node_ids[note.id] = i
    
    # Create edges from wiki-links
    for note in notes:
        source_idx = node_ids[note.id]
        linked_notes = note.get_linked_notes()
        
        for linked_note in linked_notes:
            target_idx = node_ids[linked_note.id]
            edges.append({
                'source': source_idx,
                'target': target_idx
            })
    
    return jsonify({'nodes': nodes, 'edges': edges})

@app.route('/api/create-link', methods=['POST'])
def create_link():
    data = request.json
    source_title = data.get('source_title')
    target_title = data.get('target_title')
    
    # Get the source note
    source_note = Note.query.filter_by(title=source_title).first()
    if not source_note:
        return jsonify({'success': False, 'error': 'Source note not found'})
    
    try:
        # Add the wiki link to the source note's content
        if f"[[{target_title}]]" not in source_note.content:
            if source_note.content:
                source_note.content += f"\n\n[[{target_title}]]"
            else:
                source_note.content = f"[[{target_title}]]"
            
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Link already exists'})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/preview', methods=['POST'])
def preview_markdown():
    content = request.json.get('content', '')
    md = markdown.Markdown(extensions=[
        WikiLinkExtension(),
        'fenced_code',
        'tables',
        'footnotes',
        'attr_list',
        'def_list',
        'abbr',
        'md_in_html'
    ])
    html_content = md.convert(content)
    return jsonify({'html': html_content})

@app.route('/api/notes/list')
def list_notes():
    notes = Note.query.all()
    return jsonify([{
        'id': note.id,
        'title': note.title
    } for note in notes])

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
