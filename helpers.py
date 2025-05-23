import os
import uuid
import json
import docx
import re
from supabase import create_client
from xml.etree import ElementTree as ET

# Extract shapes with details
def extract_shapes_with_details(docx_path):
    doc = docx.Document(docx_path)
    shapes_data = []

    namespaces = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
        'v': 'urn:schemas-microsoft-com:vml',
        'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
    }

    for part in doc.part.package.parts:
        if "drawingml" in part.partname or "vml" in part.partname:
            try:
                tree = ET.ElementTree(ET.fromstring(part.blob))
                root = tree.getroot()

                for shape in root.findall('.//wp:anchor|.//wp:inline|.//v:shape|.//wps:sp', namespaces):
                    shape_info = {
                        'type': shape.tag.split('}')[1] if '}' in shape.tag else shape.tag,
                        'labels': [],
                        'context': [],
                        'coordinates': {'x': None, 'y': None, 'width': None, 'height': None}
                    }

                    # Find shape type (more precise from inner shape properties)
                    shape_properties = shape.find('.//a:spPr|.//v:shape|.//wps:spPr', namespaces)
                    if shape_properties is not None:
                        shape_info['type'] = shape_properties.tag.split('}')[1] if '}' in shape_properties.tag else shape_properties.tag

                    # Attempt to extract position/size from <wp:extent> or similar
                    extent = shape.find('.//wp:extent', namespaces)
                    if extent is not None:
                        shape_info['coordinates'] = {
                            'x': None,
                            'y': None,
                            'width': extent.attrib.get('cx'),
                            'height': extent.attrib.get('cy')
                        }

                    # Extract any text inside the shape
                    text_elements = shape.findall('.//w:t|.//v:textbox//w:t|.//wps:txBody//w:t', namespaces)
                    for text_element in text_elements:
                        if text_element.text:
                            shape_info['labels'].append(text_element.text)

                    # Attempt to find the nearest paragraph as context
                    parent = shape
                    while parent is not None and parent.tag != f"{{{namespaces['w']}}}p":
                        parent = parent.getparent() if hasattr(parent, 'getparent') else None

                    if parent is not None:
                        context_texts = parent.findall('.//w:t', namespaces)
                        shape_info['context'] = [t.text for t in context_texts if t.text]

                    shapes_data.append(shape_info)

            except Exception as e:
                print(f"⚠️ Error parsing shape in {docx_path}, part {part.partname}: {e}")

    print(f"✅ Extracted {len(shapes_data)} shapes from {docx_path}")
    return shapes_data




# Parse questions from LaTeX
def clean_latex_table_formatting(text):
    """Remove LaTeX table-specific formatting while preserving content."""
    text = re.sub(r'\\(toprule|midrule|bottomrule|endhead|endfoot|hline|tabularnewline)', '', text)
    text = re.sub(r'\\\\\s*$', '', text)
    return text.strip()



def parse_questions_from_latex(text):
    longtable_pattern = r'\\begin\{longtable\}(\[[^\]]*\])?\{[^}]*\}.*?\\end\{longtable\}'

    question_blocks = re.split(r'(\\textbf\{\d+\.\})', text)
    questions = []

    for i in range(1, len(question_blocks), 2):
        prefix = question_blocks[i]
        content = question_blocks[i + 1]

        number_match = re.search(r'\\textbf\{(\d+)\.\}', prefix)
        question_number = int(number_match.group(1)) if number_match else None
        if question_number is None:
            continue

        # Find all longtables as Match objects to preserve order and positions
        longtable_matches = list(re.finditer(longtable_pattern, content, re.DOTALL))
        longtables = [m.group(0) for m in longtable_matches]

        if not longtables:
            continue

        answer_table_latex = longtables[-1]

        # Replace each longtable in content by a placeholder, in order
        question_body_parts = []
        last_index = 0
        for idx, match in enumerate(longtable_matches):
            start, end = match.span()
            # Text before this table
            question_body_parts.append(content[last_index:start])
            # Add placeholder with index to replace precisely later
            question_body_parts.append(f'<<<LONGTABLE_{idx}>>>')
            last_index = end
        # Add remaining content after last table
        question_body_parts.append(content[last_index:])
        question_body = "".join(question_body_parts)

        # Now replace placeholders for all tables except last (answer table)
        question_body_with_tables = question_body
        for idx, table_latex in enumerate(longtables[:-1]):
            placeholder = f'<<<LONGTABLE_{idx}>>>'
            question_body_with_tables = question_body_with_tables.replace(placeholder, table_latex)

        # Remove any leftover placeholders (should only be the last one for answer table)
        for idx in range(len(longtables)-1, len(longtables)):
            placeholder = f'<<<LONGTABLE_{idx}>>>'
            question_body_with_tables = question_body_with_tables.replace(placeholder, '')

        question_text = question_body_with_tables.strip()

        # Extract answer table content inside the last longtable (without environment)
        answer_table_content = re.sub(
            r'\\begin\{longtable\}(\[[^\]]*\])?\{[^}]*\}|\\end\{longtable\}',
            '',
            answer_table_latex,
            flags=re.DOTALL
        ).strip()

        is_single_column = '&' not in answer_table_content
        seen_options = {}

        if is_single_column:
            current_option = None
            current_text = []
            for line in answer_table_content.splitlines():
                line = line.strip()
                if not line or line.startswith('%'):
                    continue
                match = re.match(r'([A-Z])\.\s*(.*)', line)
                if match:
                    if current_option:
                        seen_options[current_option] = {
                            "option": current_option,
                            "choice": " ".join(current_text).strip()
                        }
                    current_option = match.group(1)
                    current_text = [match.group(2)]
                else:
                    if current_option:
                        current_text.append(line)
            if current_option:
                seen_options[current_option] = {
                    "option": current_option,
                    "choice": " ".join(current_text).strip()
                }
        else:
            flat_content = " ".join(line.strip() for line in answer_table_content.splitlines() if line.strip())
            matches = re.findall(r'([A-Z])\.\s*((?:.*?)(?=(?:[A-Z]\.\s|$)))', flat_content)
            for option, choice in matches:
                seen_options[option] = {
                    "option": option,
                    "choice": choice.strip()
                }

        table_choices = sorted(seen_options.values(), key=lambda x: x['option'])

        questions.append({
            "number": question_number,
            "question": question_text,
            "choices": table_choices
        })

    return questions

# Map shapes to content
def map_shapes_to_content(questions, answers, shapes_data):
    unmapped_shapes = shapes_data.copy()
    for shape in shapes_data:
        context = " ".join(shape.get('labels', []) + shape.get('context', [])).lower()
        matched = False

        number_match = re.search(r'\b(\d+)\b', context)
        if number_match:
            num = int(number_match.group(1))
            for q in questions:
                if q["number"] == num:
                    q.setdefault("shapes", []).append(shape)
                    unmapped_shapes.remove(shape)
                    print(f"✅ Mapped shape to question {num}: {context[:30]}...")
                    matched = True
                    break
            if not matched and num in answers:
                answers[num]["shapes"].append(shape)
                unmapped_shapes.remove(shape)
                print(f"✅ Mapped shape to answer {num}: {context[:30]}...")
                matched = True

        if not matched:
            for q in questions:
                if context and context in q["question"].lower():
                    q.setdefault("shapes", []).append(shape)
                    unmapped_shapes.remove(shape)
                    print(f"✅ Substring-mapped shape to question {q['number']}: {context[:30]}...")
                    matched = True
                    break
            if not matched:
                for num, ans in answers.items():
                    if context and context in ans.get("explanation", "").lower():
                        ans["shapes"].append(shape)
                        unmapped_shapes.remove(shape)
                        print(f"✅ Substring-mapped shape to answer {num}: {context[:30]}...")
                        matched = True
                        break

    for shape in unmapped_shapes:
        if questions:
            questions[-1].setdefault("shapes", []).append(shape)
            print(f"✅ Assigned unmapped shape to question {questions[-1]['number']}: {shape['labels'][:30]}...")
        elif answers:
            last_num = max(answers.keys())
            answers[last_num]["shapes"].append(shape)
            print(f"✅ Assigned unmapped shape to answer {last_num}: {shape['labels'][:30]}...")

    return questions, answers

# Parse answers


def parse_answers(text, shapes_data):
    answer_map = {}

    # Updated pattern: captures answer as any string (not just A/B/C/D)
    pattern = re.compile(
        r'(?:(?:\\textbf\{(\d+)\.\})|(\d+)[.\s]*)\s*'  # Question number handling
        r'(.*?)'                                      # Pre-quote explanation
        r'(?:\\begin\{quote\}(.*?)\\end\{quote\})?'    # Optional quote block
        r'\s*\\textbf\{Answer\}:\s*([^\n■\\]+)',       # Answer (non-restrictive)
        re.DOTALL
    )



    matches = pattern.finditer(text)
    match_count = 0  # Count how many matches were found

    for match in matches:
        match_count += 1
        bold_num, plain_num, pre_quote_text, quote_text, answer = match.groups()
        print(f"Match groups: {match.groups()}")

        num = int(bold_num or plain_num) if (bold_num or plain_num) else None
        if num is None:
            print(f"⚠️ No answer number found for section: {pre_quote_text[:30]}...")
            continue

        pre_quote_text = pre_quote_text.strip() if pre_quote_text else ""
        quote_text = quote_text.strip() if quote_text else ""
        explanation = pre_quote_text + ("\n" + quote_text if pre_quote_text and quote_text else quote_text)

        # Clean and normalize the answer
        answer_value = answer.strip() if answer else None
        if answer_value not in ['A', 'B', 'C', 'D', 'No Answer is given']:
            print(f"⚠️ Unrecognized answer for question {num}: '{answer_value}'")
            answer_value = None  # Or "No Answer" if preferred

        # Shape references
        shape_refs = re.findall(r'Shape\s*[\w.-]*(\d+)', explanation, re.IGNORECASE)
        shape_list = []
        for shape_index in shape_refs:
            shape_index = int(shape_index) - 1
            if 0 <= shape_index < len(shapes_data):
                shape_list.append(shapes_data[shape_index])
            else:
                print(f"⚠️ Shape {shape_index + 1} referenced in answer {num} is out of bounds (max: {len(shapes_data)})")

        answer_map[num] = {
            "answer": answer_value,
            "explanation": explanation,
            "shapes": shape_list
        }
        print(f"✅ Parsed answer {num}: {answer_value}, Explanation: {explanation[:30]}..., Shapes: {len(shape_list)}")

    if match_count == 0:
        print("⚠️ No matches found for answers in the provided text!")

    return answer_map







def convert_docx_to_latex(docx_filename, output_tex_filename):
    os.system(f"pandoc '{docx_filename}' -f docx -t latex -o '{output_tex_filename}'")
    with open(output_tex_filename, "r", encoding="utf-8") as f:
        latex_text = f.read()
    return latex_text



# Batch insert MCQs to Supabase


def upload_mcqs_batch(questions, answers, subject, year, supabase, shapes_data ,testId):
    records = []

    for q in questions:
        question_num = q.get("number")
        if question_num is None:
            print(f"⚠️ Skipping question with no number: {q['question'][:30]}...")
            continue
        print("hereeeee")
        # Attach answer + explanation from answer map
        if question_num in answers:
            q.update({
                "answer": answers[question_num]["answer"],
                "explanation": answers[question_num]["explanation"],
            })
            print(f"✅ Mapped answer to question {question_num}: {q['answer'] or 'None'}")
        else:
            q.update({
                "answer": None,
                "explanation": None,
            })
            print(f"⚠️ No answer found for question {question_num}: {q['question'][:30]}...")

        # Prepare record with custom ID, subject, and year fields
        records.append({
            "id": str(uuid.uuid4()),  # ✅ Random unique ID
            "question_number": question_num,  # ✅ New field
            "question_text": q["question"],
            "options": json.dumps(q["choices"]),
            "correct_answer": q["answer"],
            "explanation": q["explanation"],
            "subject": subject,
            "year": year,
            "test_id": testId# Add year to the record
        })

    # Upload logic with retries
    for i in range(3):
        try:
            response = supabase.table("questions").insert(records).execute()
            if hasattr(response, 'data') and response.data:
                print(f"✅ Uploaded {len(records)} questions successfully!")
                return
            else:
                print(f"❌ Upload failed. Supabase response: {response}")
        except Exception as e:
            print(f"⚠️ Upload attempt {i+1} failed: {e}")

    print("❌ All upload attempts failed")
