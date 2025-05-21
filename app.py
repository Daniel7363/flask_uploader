from flask import Flask, request, jsonify
from flask_cors import CORS
from helpers import  extract_shapes_with_details, parse_questions_from_latex, parse_answers, upload_mcqs_batch , map_shapes_to_content
from supabase import create_client
import os
from dotenv import load_dotenv
app = Flask(__name__)
CORS(app, origins=["http://localhost:8080", "https://your-production-site.com"])

# Load .env variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variable")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

import tempfile

@app.route('/api/process', methods=['POST'])
def process_files():
    if 'question_file' not in request.files or 'answer_file' not in request.files:
        return jsonify({"error": "Missing files for questions or answers"}), 400

    question_file = request.files['question_file']
    answer_file = request.files['answer_file']
    data = request.form  # use form-data for files and fields

    subject = data.get('subject', '')
    year = data.get('year', '')

    try:
        # Save uploaded files temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as qf, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as af:

            question_file.save(qf.name)
            answer_file.save(af.name)

            question_shapes = extract_shapes_with_details(qf.name)
            answer_shapes = extract_shapes_with_details(af.name)
            all_shapes = question_shapes + answer_shapes

            # Convert docx to LaTeX
            from helpers import convert_docx_to_latex
            questions_tex = convert_docx_to_latex(qf.name, "temp_q.tex")
            answers_tex = convert_docx_to_latex(af.name, "temp_a.tex")

            questions = parse_questions_from_latex(questions_tex)
            answers = parse_answers(answers_tex, all_shapes)

            questions, answers = map_shapes_to_content(questions, answers, all_shapes)
            upload_mcqs_batch(questions, answers, subject, year, supabase, all_shapes)

        return jsonify({"message": "Files processed successfully"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

