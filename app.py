import os
import io
import json
from datetime import datetime
from typing import List, Dict
import random
import matplotlib
matplotlib.use('Agg')

from flask import Response
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from flask import Flask, request, jsonify, Response

import nltk
nltk.download('punkt')

import matplotlib.pyplot as plt
from flask import Flask, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
import speech_recognition as sr
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from keybert import KeyBERT
import pytextrank
import spacy
import numpy as np
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import base64

flashcard_generator = pipeline("text-generation", model="gpt2")
qa_pipeline = pipeline("question-answering", model="deepset/roberta-base-squad2")



app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['STATIC_FOLDER'] = 'static'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize NLP models
summarizer = pipeline('summarization', model='sshleifer/distilbart-cnn-12-6', revision='a4f8f3e')
sentiment_analyzer = pipeline('sentiment-analysis', model='distilbert-base-uncased-finetuned-sst-2-english')
keyword_model = KeyBERT()

# Initialize translation model
translator = AutoModelForSeq2SeqLM.from_pretrained("Helsinki-NLP/opus-mt-en-ROMANCE")
translator_tokenizer = AutoTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-ROMANCE")

# Initialize spaCy for advanced NLP
nlp = spacy.load("en_core_web_sm")
nlp.add_pipe("textrank")

class NoteTakingHistory:
    def __init__(self):
        self.history = {}
        
    def add_note(self, note_id: str, content: Dict):
        self.history[note_id] = {
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'version': 1
        }
    
    def get_note(self, note_id: str) -> Dict:
        return self.history.get(note_id)

note_history = NoteTakingHistory()

@app.route('/')
def index():
    return send_from_directory(os.getcwd(), 'index.html')

@app.route('/process-audio', methods=['POST'])
def process_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    filename = secure_filename(audio_file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    audio_file.save(save_path)

    # Process audio with noise reduction and enhanced recognition
    transcription = enhanced_transcribe_audio(save_path)
    
    # Generate multiple summaries with different perspectives
    summaries = generate_smart_summaries(transcription)
    
    # Extract key insights
    insights = extract_key_insights(transcription)
    
    # Generate unique note ID
    note_id = generate_note_id()
    
    # Store in history
    note_history.add_note(note_id, {
        'transcription': transcription,
        'summaries': summaries,
        'insights': insights
    })

    return jsonify({
        'note_id': note_id,
        'transcription': transcription,
        'summaries': summaries,
        'insights': insights
    })

#added flashgen


def enhanced_transcribe_audio(file_path):
    recognizer = sr.Recognizer()
    
    # Enhanced noise reduction
    with sr.AudioFile(file_path) as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio = recognizer.record(source)
        
    try:
        # Try multiple recognition engines and pick the best result
        results = []
        try:
            results.append(recognizer.recognize_google(audio))
        except Exception:
            pass
        
        try:
            results.append(recognizer.recognize_sphinx(audio))
        except Exception:
            pass
        
        if not results:
            return "Sorry, I could not understand the audio."
            
        # Return the longest transcription as it's likely the most complete
        return max(results, key=len)
        
    except Exception as e:
        return f"Error during transcription: {str(e)}"

def generate_smart_summaries(text):
    if not text.strip():
        return {"error": "No content to summarize"}
    
    # Generate multiple summary types
    summaries = {
        "brief": summarizer(text, max_length=50, min_length=20, do_sample=False)[0]['summary_text'],
        "detailed": summarizer(text, max_length=150, min_length=50, do_sample=False)[0]['summary_text'],
        "key_points": extract_key_points(text),
        "action_items": extract_action_items(text)
    }
    
    return summaries

def extract_key_insights(text):
    doc = nlp(text)
    
    insights = {
        "key_phrases": [phrase.text for phrase in doc._.phrases[:5]],
        "entities": [{'text': ent.text, 'type': ent.label_} for ent in doc.ents],
        "sentiment": sentiment_analyzer(text)[0],
        "readability_score": calculate_readability(text)
    }
    
    return insights

@app.route('/generate-mindmap', methods=['POST'])
def generate_mindmap():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text.strip():
        return jsonify({'error': 'No text provided'}), 400
        
    # Generate an enhanced mind map data structure
    mindmap = generate_enhanced_mindmap(text)
    return jsonify({'mindmap': mindmap})

def generate_enhanced_mindmap(text):
    doc = nlp(text)
    mind_map = []
    
    # Attempt to extract main topics using sentence-level dependency parsing
    for sent in doc.sents:
        subject = None
        subtopics = []
        for token in sent:
            # Identify subjects as potential main topics
            if token.dep_ in ("nsubj", "nsubjpass") and not token.is_stop:
                subject = token.lemma_
            # Capture objects, attributes, and complements as subtopics
            if token.dep_ in ("dobj", "pobj", "attr", "acomp") and not token.is_stop:
                subtopics.append(token.lemma_)
        # Only add if we have a valid subject that's not trivial
        if subject and subject.lower() not in ("it", "this", "that", "he", "she", "they", "we", "i"):
            # Deduplicate subtopics and filter generic words
            subtopics = list(set([st for st in subtopics if len(st) > 1]))
            mind_map.append({
                'main': subject,
                'subtopics': subtopics
            })
    
    # Fallback: if no clear subject was found, use noun chunks for extraction
    if not mind_map:
        for chunk in doc.noun_chunks:
            main_topic = chunk.root.lemma_
            subtopics = [token.lemma_ for token in chunk if not token.is_stop and token.dep_ not in ("punct")]
            if main_topic.lower() not in ("it", "this", "that", "he", "she", "they", "we", "i"):
                mind_map.append({
                    'main': main_topic,
                    'subtopics': list(set(subtopics))
                })
    return mind_map


@app.route('/translate', methods=['POST'])
def translate_text():
    data = request.get_json()
    text = data.get('text', '')
    target_lang = data.get('target_lang', 'es')  # Default to Spanish
    
    if not text.strip():
        return jsonify({'error': 'No text provided'}), 400
    
    # Translate text
    inputs = translator_tokenizer(text, return_tensors="pt")
    outputs = translator.generate(**inputs)
    translation = translator_tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    return jsonify({'translation': translation})

@app.route('/analyze-text', methods=['POST'])
def analyze_text():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text.strip():
        return jsonify({'error': 'No text provided'}), 400
    
    # Comprehensive text analysis
    doc = nlp(text)
    
    analysis = {
        'summary': generate_smart_summaries(text),
        'keywords': extract_smart_keywords(text),
        'sentiment': sentiment_analyzer(text)[0],
        'entities': [{'text': ent.text, 'type': ent.label_} for ent in doc.ents],
        'readability': calculate_readability(text),
        'language_stats': calculate_language_stats(doc)
    }
    
    return jsonify(analysis)

def extract_smart_keywords(text):
    # Combine multiple keyword extraction methods
    keybert_keywords = keyword_model.extract_keywords(text, keyphrase_ngram_range=(1, 2), top_n=5)
    
    doc = nlp(text)
    textrank_keywords = [phrase.text for phrase in doc._.phrases[:5]]
    
    # Combine and deduplicate keywords
    all_keywords = list(set([kw for kw, _ in keybert_keywords] + textrank_keywords))
    return all_keywords[:10]  # Return top 10 unique keywords

def calculate_readability(text):
    doc = nlp(text)
    words = len([token for token in doc if not token.is_punct])
    sentences = len(list(doc.sents))
    syllables = sum([len([char for char in token.text if char.lower() in 'aeiou']) 
                    for token in doc if not token.is_punct])
    
    if sentences == 0 or words == 0:
        return 0
        
    # Calculate Flesch Reading Ease score
    score = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
    return round(score, 2)

def calculate_language_stats(doc):
    sentence_lengths = [len([token for token in sent if not token.is_punct]) for sent in doc.sents]
    return {
        'sentence_count': len(list(doc.sents)),
        'word_count': len([token for token in doc if not token.is_punct]),
        'unique_words': len(set([token.text.lower() for token in doc if not token.is_punct])),
        'avg_sentence_length': float(np.mean(sentence_lengths)) if sentence_lengths else 0
    }

def generate_note_id():
    return f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"

def extract_key_points(text):
    doc = nlp(text)
    return [sent.text for sent in doc.sents 
            if any(token.dep_ in ('nsubj', 'dobj') for token in sent)][:3]

def extract_action_items(text):
    doc = nlp(text)
    action_items = []
    
    for sent in doc.sents:
        # Look for sentences that start with verbs or contain action-oriented words
        if (sent[0].pos_ == 'VERB' or 
            any(token.text.lower() in ['need', 'must', 'should', 'todo', 'action'] 
                for token in sent)):
            action_items.append(sent.text)
    
    return action_items[:3]

@app.route('/download-enhanced-pdf', methods=['POST'])
def download_enhanced_pdf():
    data = request.get_json()
    note_id = data.get('note_id')
    
    if not note_id:
        return jsonify({'error': 'Note ID not provided'}), 400
        
    note_data = note_history.get_note(note_id)
    if not note_data:
        return jsonify({'error': 'Note not found'}), 404

    # Create PDF with enhanced styling
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom styles
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30
    ))
    
    # Build PDF content
    content = []
    
    # Title
    content.append(Paragraph("Enhanced Note Summary", styles['CustomTitle']))
    content.append(Spacer(1, 12))
    
    # Add each section with proper styling
    sections = [
        ("Transcription", note_data['content']['transcription']),
        ("Smart Summaries", format_summaries(note_data['content']['summaries'])),
        ("Key Insights", format_insights(note_data['content']['insights']))
    ]
    
    for title, text in sections:
        content.append(Paragraph(title, styles['Heading1']))
        content.append(Spacer(1, 12))
        content.append(Paragraph(text, styles['Normal']))
        content.append(Spacer(1, 20))
    
    # Generate and add word cloud image
    if note_data['content']['transcription']:
        wordcloud_image = generate_wordcloud(note_data['content']['transcription'])
        content.append(Paragraph("Word Cloud Visualization", styles['Heading1']))
        content.append(Spacer(1, 12))
        content.append(wordcloud_image)
    
    # Build PDF
    doc.build(content)
    pdf_buffer.seek(0)
    
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"enhanced_notes_{note_id}.pdf",
        mimetype='application/pdf'
    )

def generate_wordcloud(text):
    # Generate the word cloud
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    
    # Save the word cloud image to a buffer using matplotlib
    img_buffer = io.BytesIO()
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(img_buffer, format='png')
    plt.close()
    
    # Reset buffer position
    img_buffer.seek(0)
    
    # Create a ReportLab Image flowable from the buffer
    img = RLImage(img_buffer, width=500, height=250)
    return img

import nltk
from nltk.tokenize import sent_tokenize
import random

# Download required NLTK data
nltk.download('punkt')

def extract_key_sentences(text):
    """
    Extract sentences that are likely to contain important information:
    - Definitions
    - Key concepts
    - Processes
    - Examples
    - Results/Conclusions
    """
    # Split into sentences
    sentences = [s.strip() for s in text.split('.') if len(s.strip()) > 10]
    
    key_sentences = []
    
    for sentence in sentences:
        # Look for indicator phrases
        indicators = [
            'is defined as', 'refers to', 'means', 'is a', 'are',  # Definitions
            'for example', 'such as', 'like',  # Examples
            'therefore', 'thus', 'as a result',  # Conclusions
            'first', 'second', 'finally', 'next',  # Process steps
            'important', 'key', 'significant', 'main',  # Key points
            'because', 'due to', 'leads to'  # Cause and effect
        ]
        
        if any(indicator in sentence.lower() for indicator in indicators):
            key_sentences.append(sentence)
    
    return key_sentences

def generate_question_from_sentence(sentence):
    """
    Generate a question-answer pair from a sentence based on its type
    """
    sentence = sentence.strip()
    
    # Definition pattern
    if any(x in sentence.lower() for x in ['is defined as', 'refers to', 'means', 'is a']):
        match = re.split(r'is defined as|refers to|means|is a', sentence, flags=re.IGNORECASE)
        if len(match) >= 2:
            return {
                'question': f"What is {match[0].strip()}?",
                'answer': match[1].strip()
            }
    
    # Process/Method pattern
    if any(x in sentence.lower() for x in ['by', 'through', 'using', 'step']):
        return {
            'question': f"How does {sentence.split()[0]} work?",
            'answer': sentence
        }
    
    # Cause and Effect pattern
    if any(x in sentence.lower() for x in ['because', 'due to', 'leads to', 'results in']):
        return {
            'question': f"What is the reason for {sentence.split()[0]}?",
            'answer': sentence
        }
    
    # Example pattern
    if any(x in sentence.lower() for x in ['for example', 'such as', 'like']):
        return {
            'question': "Can you provide an example from the context?",
            'answer': sentence
        }
    
    # Fallback: Create a "what" question
    words = sentence.split()
    if len(words) > 3:
        key_term = ' '.join(words[:2])
        return {
            'question': f"What {words[1]} {' '.join(words[2:])}?",
            'answer': sentence
        }
    
    return None

def generate_flashcards_from_content(text):
    """
    Generate flashcards by analyzing content and creating relevant Q&A pairs
    """
    try:
        # Clean the text
        text = text.replace('\n', ' ').strip()
        
        # Extract key sentences
        key_sentences = extract_key_sentences(text)
        
        # Generate questions from key sentences
        flashcards = []
        for sentence in key_sentences:
            qa_pair = generate_question_from_sentence(sentence)
            if qa_pair:
                flashcards.append(qa_pair)
        
        # If we don't have enough questions, generate some from remaining content
        if len(flashcards) < 3:
            # Split remaining text into chunks
            chunks = [s.strip() + '.' for s in text.split('.') if len(s.strip()) > 20]
            for chunk in chunks:
                if len(flashcards) >= 5:  # Limit to 5 flashcards
                    break
                    
                words = chunk.split()
                if len(words) > 5:
                    # Create a fill-in-the-blank question
                    remove_idx = len(words) // 2
                    answer = words[remove_idx]
                    words[remove_idx] = "_____"
                    
                    flashcard = {
                        'question': f"Complete this statement: {' '.join(words)}",
                        'answer': f"The missing word is: {answer}"
                    }
                    flashcards.append(flashcard)
        
        return flashcards
        
    except Exception as e:
        print(f"Error in generate_flashcards_from_content: {str(e)}")
        return []

@app.route('/generate-flashcards', methods=['POST'])
def generate_flashcards_endpoint():
    try:
        data = request.get_json()
        note_id = data.get('note_id')
        
        if not note_id:
            return jsonify({'error': 'Note ID not provided'}), 400
            
        note_data = note_history.get_note(note_id)
        print(f"Retrieved note data: {note_data}")  # Debug print
        
        if not note_data:
            return jsonify({'error': 'Note not found'}), 404
            
        text = note_data.get('content', {}).get('transcription', '')
        if not text:
            return jsonify({'error': 'No transcription available'}), 400
            
        flashcards = generate_flashcards_from_content(text)
        
        if not flashcards:
            return jsonify({'error': 'Could not generate questions from the content'}), 400
            
        return jsonify({'flashcards': flashcards})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Flashcard generation failed', 'details': str(e)}), 500

@app.route('/ask-question', methods=['POST'])
def ask_question():
    data = request.get_json()
    note_id = data.get('note_id')
    question = data.get('question')
    if not note_id or not question:
        return jsonify({'error': 'Note ID and question are required'}), 400
    note_data = note_history.get_note(note_id)
    if not note_data:
        return jsonify({'error': 'Note not found'}), 404
    context = note_data['content']['transcription']
    answer = qa_pipeline(question=question, context=context)
    return jsonify({'answer': answer})



def format_summaries(summaries):
    return "\n\n".join([
        f"{title.upper()}:\n{content}"
        for title, content in summaries.items()
    ])

def format_insights(insights):
    return "\n\n".join([
        f"{title.upper()}:\n{str(content)}"
        for title, content in insights.items()
    ])
    
   #added one more feature 
   
   # Add these imports to your existing app.py
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlparse
import re


def extract_qa_content(url: str) -> List[Dict[str, str]]:
    """
    Extract Q&A content from a given URL with improved handling for programming questions.
    Returns a list of dictionaries containing question-answer pairs.
    """
    def clean_text(text: str) -> str:
        """Clean and normalize text content."""
        return re.sub(r'\s+', ' ', text).strip()

    def is_valid_qa(question: str, answer: str) -> bool:
        """
        Validate if the Q&A pair is meaningful.
        """
        if not question or not answer:
            return False
        
        # Minimum lengths for valid content
        if len(question) < 10 or len(answer) < 5:
            return False
            
        # Avoid cases where answer is just "Example" or similar
        low_quality_answers = {'example', 'example:', 'example 1', 'example 2'}
        if answer.lower().strip() in low_quality_answers:
            return False
            
        return True

    def extract_code_block(element) -> str:
        """Extract code blocks if present in the answer."""
        code_blocks = element.find_all(['pre', 'code'])
        if code_blocks:
            return '\n'.join(block.get_text(strip=True) for block in code_blocks)
        return ''

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        qa_pairs = []

        # Strategy 1: Look for numbered questions pattern
        question_patterns = [
            r'^\d+[\)\.]\s+',  # Matches "1) " or "1. "
            r'^Q\d+[\)\.]\s+',  # Matches "Q1) " or "Q1. "
            r'^Question\s+\d+[\)\.]\s+'  # Matches "Question 1) " or "Question 1. "
        ]

        for element in soup.find_all(['p', 'div', 'h2', 'h3', 'h4']):
            text = clean_text(element.get_text())
            
            # Check if this element contains a question
            is_question = any(re.match(pattern, text) for pattern in question_patterns)
            
            if is_question:
                # Find the answer in subsequent elements
                answer_element = element.find_next(['p', 'div', 'pre', 'code'])
                if answer_element:
                    answer_text = clean_text(answer_element.get_text())
                    code_block = extract_code_block(answer_element)
                    
                    # Combine regular text and code block if both exist
                    full_answer = answer_text
                    if code_block:
                        full_answer = f"{answer_text}\n\nCode:\n{code_block}"
                    
                    if is_valid_qa(text, full_answer):
                        qa_pairs.append({
                            'question': text,
                            'answer': full_answer
                        })

        # Strategy 2: Look for question-answer pairs in structured formats
        qa_containers = soup.find_all(['div', 'section'], class_=re.compile(r'(question|answer|qa|faq)'))
        for container in qa_containers:
            question_elem = container.find(['h2', 'h3', 'h4', 'div', 'p'], class_=re.compile(r'question|q'))
            answer_elem = container.find(['div', 'p', 'pre'], class_=re.compile(r'answer|a'))
            
            if question_elem and answer_elem:
                question_text = clean_text(question_elem.get_text())
                answer_text = clean_text(answer_elem.get_text())
                code_block = extract_code_block(answer_elem)
                
                if code_block:
                    answer_text = f"{answer_text}\n\nCode:\n{code_block}"
                
                if is_valid_qa(question_text, answer_text):
                    qa_pairs.append({
                        'question': question_text,
                        'answer': answer_text
                    })

        # Remove duplicates while preserving order
        seen = set()
        unique_qa_pairs = []
        for qa in qa_pairs:
            qa_tuple = (qa['question'], qa['answer'])
            if qa_tuple not in seen:
                seen.add(qa_tuple)
                unique_qa_pairs.append(qa)

        if not unique_qa_pairs:
            raise ValueError("No valid Q&A content found on the page")

        return unique_qa_pairs

    except requests.RequestException as e:
        raise ValueError(f"Failed to access the website: {str(e)}")
    except Exception as e:
        raise ValueError(f"Failed to extract Q&A content: {str(e)}")


@app.route('/extract-qa-from-url', methods=['POST'])
def extract_qa_from_url():
    try:
        data = request.get_json()
        url = data.get('url')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # Extract Q&A content
        try:
            qa_pairs = extract_qa_content(url)
        except ValueError as e:
            return jsonify({'error': str(e)}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        # Generate unique note ID for storage
        note_id = generate_note_id()

        # Store in history
        note_history.add_note(note_id, {
            'content_type': 'qa_extraction',
            'source_url': url,
            'qa_pairs': qa_pairs,
            'transcription': '\n\n'.join([f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs])
        })

        # ✅ Print note_id and stored data for debugging
        print(f"Stored note_id: {note_id}")
        print(f"Stored data: {note_history.get_note(note_id)}")

        return jsonify({
            'note_id': note_id,
            'qa_pairs': qa_pairs,
            'message': 'Q&A content extracted successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def draw_wrapped_text(pdf, text, x, y, max_width, line_height):
    """
    Draw text on the canvas, wrapping it within max_width.
    Returns the new y position after drawing the text.
    """
    words = text.split()
    line = ""
    for word in words:
        test_line = f"{line} {word}".strip()
        # Check if the test_line width is within max_width
        if pdf.stringWidth(test_line, pdf._fontname, pdf._fontsize) < max_width:
            line = test_line
        else:
            pdf.drawString(x, y, line)
            y -= line_height
            line = word
    if line:
        pdf.drawString(x, y, line)
        y -= line_height
    return y

@app.route('/download-qa-pdf/<note_id>', methods=['GET'])
def download_qa_pdf(note_id):
    try:
        print(f"Received note_id for PDF: {note_id}")

        # Retrieve stored note data
        note_data = note_history.get_note(note_id)
        print(f"Retrieved note data: {note_data}")

        if not note_data:
            return jsonify({'error': 'No data found for the given note ID'}), 404

        # Access the nested 'content' where the Q&A is stored
        content = note_data.get('content', {})
        if 'qa_pairs' not in content:
            return jsonify({'error': 'No Q&A content found for the given note ID'}), 404

        qa_pairs = content['qa_pairs']

        # Create an in-memory PDF file
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle("Extracted Q&A")

        # Define starting positions and layout parameters
        y_position = 750
        left_margin = 50
        right_margin = 50
        max_width = letter[0] - left_margin - right_margin
        line_height = 14

        # Title
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, y_position, "Extracted Q&A")
        y_position -= 30

        pdf.setFont("Helvetica", 12)
        for qa in qa_pairs:
            # Check if space is available; if not, start a new page.
            if y_position < 100:
                pdf.showPage()
                pdf.setFont("Helvetica", 12)
                y_position = 750

            # Draw the question (using bold font)
            pdf.setFont("Helvetica-Bold", 12)
            question_text = f"Q: {qa['question']}"
            y_position = draw_wrapped_text(pdf, question_text, left_margin, y_position, max_width, line_height)
            
            # Add a little spacing between question and answer
            y_position -= 4
            
            # Draw the answer (regular font)
            pdf.setFont("Helvetica", 12)
            answer_text = f"A: {qa['answer']}"
            y_position = draw_wrapped_text(pdf, answer_text, left_margin, y_position, max_width, line_height)
            
            # Additional spacing after each Q&A block
            y_position -= 10

        pdf.save()
        buffer.seek(0)

        return Response(
            buffer,
            mimetype='application/pdf',
            headers={
                "Content-Disposition": f"attachment; filename=Extracted_QA_{note_id}.pdf"
            }
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500




if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)


