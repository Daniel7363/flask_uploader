from flask import Flask, request, jsonify
from helpers import get_file, extract_shapes_with_details, parse_questions_from_latex, parse_answers, upload_mcqs_batch
from supabase import create_client
import os
from dotenv import load_dotenv
app = Flask(__name__)

# Load .env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/api/process', methods=['POST'])
def process_files():
    # Check if the request contains the files
    if 'question_file' not in request.files or 'answer_file' not in request.files:
        return jsonify({"error": "Missing files for questions or answers"}), 400

    question_file = request.files['question_file']
    answer_file = request.files['answer_file']
    
    # Extract shapes and parse questions/answers
    try:
        question_shapes = extract_shapes_with_details(question_file)
        answer_shapes = extract_shapes_with_details(answer_file)
        all_shapes = question_shapes + answer_shapes
        
        questions_tex = question_file.read().decode('utf-8')
        answers_tex = answer_file.read().decode('utf-8')

        questions = parse_questions_from_latex(questions_tex)
        answers = parse_answers(answers_tex, all_shapes)

        # Map shapes to content
        questions, answers = map_shapes_to_content(questions, answers, all_shapes)

        # Get subject and year from the JSON payload
        data = request.json
        subject = data.get('subject', '')
        year = data.get('year', '')

        # Upload to Supabase
        upload_mcqs_batch(questions, answers, subject, year, supabase, all_shapes)

        return jsonify({"message": "Files processed successfully", "questions": questions, "answers": answers})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

