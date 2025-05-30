import os
import jwt
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client
from helpers import extract_shapes_with_details, parse_questions_from_latex, parse_answers, upload_mcqs_batch, map_shapes_to_content

# Load environment variables
load_dotenv()

# Initialize Flask app and CORS
app = Flask(__name__)
CORS(app, origins=["http://localhost:8080", "https://your-production-site.com"])

# Supabase client
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# JWT settings
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

def verify_admin_token():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.replace("Bearer ", "").strip()
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if decoded.get("role") != "the big boss, the man, the myth, the legend":
            return jsonify({"error": "Forbidden"}), 403
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 403

    return None

@app.route('/api/process', methods=['POST'])
def process_files():
    # Verify admin token
    auth_error = verify_admin_token()
    if auth_error:
        return auth_error

    if 'question_file' not in request.files or 'answer_file' not in request.files:
        return jsonify({"error": "Missing files for questions or answers"}), 400

    question_file = request.files['question_file']
    answer_file = request.files['answer_file']
    data = request.form

    subject = data.get('subject', '')
    year = data.get('year', '')
    testId = data.get('test_id', '')

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as qf, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as af:

            question_file.save(qf.name)
            answer_file.save(af.name)

            question_shapes = extract_shapes_with_details(qf.name)
            answer_shapes = extract_shapes_with_details(af.name)
            all_shapes = question_shapes + answer_shapes

            from helpers import convert_docx_to_latex
            questions_tex = convert_docx_to_latex(qf.name, "temp_q.tex")
            answers_tex = convert_docx_to_latex(af.name, "temp_a.tex")

            questions = parse_questions_from_latex(questions_tex)
            answers = parse_answers(answers_tex, all_shapes)

            questions, answers = map_shapes_to_content(questions, answers, all_shapes)
            upload_mcqs_batch(questions, answers, subject, year, supabase, all_shapes, testId)

        return jsonify({"message": "Files processed successfully"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
