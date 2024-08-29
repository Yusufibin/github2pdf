import os
import sys
import requests
import zipfile
import io
from typing import List
import argparse
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

def is_binary(file_content):
    """Check if file content is likely binary."""
    return b'\0' in file_content[:1024]

def is_markdown_file(file_path: str) -> bool:
    """Check if the file is a Markdown file."""
    return file_path.lower().endswith('.md')

def is_likely_useful_file(file_path):
    """Determine if the file is likely to be useful by excluding certain directories and specific file types."""
    excluded_dirs = ["examples", "tests", "test", "scripts", "utils", "benchmarks", "__pycache__", "vendor"]
    utility_or_config_files = ["hubconf.py", "setup.py", "go.mod", "go.sum", "Makefile"]
    github_workflow_or_docs = [".github", ".gitignore", "LICENSE", "README"]

    if any(part.startswith('.') for part in file_path.split('/')):
        return False
    if 'test' in file_path.lower():
        return False
    for excluded_dir in excluded_dirs:
        if f"/{excluded_dir}/" in file_path or file_path.startswith(excluded_dir + "/"):
            return False
    for file_name in utility_or_config_files:
        if file_name in file_path:
            return False
    for doc_file in github_workflow_or_docs:
        if doc_file in file_path:
            return False
    return True

def has_sufficient_content(file_content, min_line_count=10):
    """Check if the file has a minimum number of substantive lines."""
    lines = [line for line in file_content.split('\n') if line.strip() and not line.strip().startswith(('#', '//'))]
    return len(lines) >= min_line_count

def download_repo(repo_url, branch_or_tag="master"):
    """Download and process files from a GitHub repository."""
    download_url = f"{repo_url}/archive/refs/heads/{branch_or_tag}.zip"
    response = requests.get(download_url)

    if response.status_code == 200:
        zip_file = zipfile.ZipFile(io.BytesIO(response.content))
        content = []
        for file_path in zip_file.namelist():
            if file_path.endswith("/") or not is_likely_useful_file(file_path) or is_markdown_file(file_path):
                continue
            file_content = zip_file.read(file_path)
            if is_binary(file_content):
                continue
            try:
                file_content = file_content.decode("utf-8")
            except UnicodeDecodeError:
                continue  # Skip files that can't be decoded as UTF-8
            if has_sufficient_content(file_content):
                content.append((file_path, file_content))
        return content
    else:
        print(f"Failed to download the repository. Status code: {response.status_code}")
        sys.exit(1)

def create_pdf(content, output_file):
    doc = SimpleDocTemplate(output_file, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    code_style = styles["Code"]
    code_style.fontSize = 8
    story = []

    for file_path, file_content in content:
        story.append(Paragraph(f"File: {file_path}", styles['Heading2']))
        story.append(Spacer(1, 12))
        story.append(Preformatted(file_content, code_style))
        story.append(Spacer(1, 24))

    doc.build(story)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Download and process all non-Markdown files from a GitHub repository into a PDF.')
    parser.add_argument('repo_url', type=str, help='The URL of the GitHub repository')
    parser.add_argument('--branch_or_tag', type=str, help='The branch or tag of the repository to download', default="master")

    args = parser.parse_args()
    output_file = f"{args.repo_url.split('/')[-1]}_all_files.pdf"

    content = download_repo(args.repo_url, args.branch_or_tag)
    create_pdf(content, output_file)
    print(f"All non-Markdown files from the repository have been saved to {output_file}")
