import os
import sys
import requests
import zipfile
import io
import re
from typing import List, Tuple, Optional
import argparse
import logging
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GithubToPDF:
    def __init__(self, repo_url: str, branch_or_tag: str = "main", output_file: Optional[str] = None, 
                 page_size: str = "A4", min_line_count: int = 5, lang_filter: Optional[str] = None,
                 exclude_patterns: Optional[List[str]] = None):
        """
        Initialise le convertisseur GitHub vers PDF.
        
        Args:
            repo_url: URL du dépôt GitHub
            branch_or_tag: Branche ou tag à utiliser
            output_file: Nom du fichier PDF de sortie
            page_size: Taille de page ('A4' ou 'letter')
            min_line_count: Nombre minimum de lignes pour inclure un fichier
            lang_filter: Filtre optionnel par langage (extension de fichier)
            exclude_patterns: Patterns regex additionnels à exclure
        """
        self.repo_url = repo_url
        self.branch_or_tag = branch_or_tag
        self.repo_name = repo_url.rstrip('/').split('/')[-1]
        self.output_file = output_file or f"{self.repo_name}_{branch_or_tag}.pdf"
        self.page_size = A4 if page_size.upper() == "A4" else letter
        self.min_line_count = min_line_count
        self.lang_filter = lang_filter
        self.exclude_patterns = exclude_patterns or []
        
        # Patterns d'exclusion par défaut
        self.excluded_dirs = [
            "examples", "tests", "test", "scripts", "utils", "benchmarks", "__pycache__", 
            "vendor", "node_modules", "dist", "build", "target", "venv", "env"
        ]
        self.excluded_files = [
            "hubconf.py", "setup.py", "go.mod", "go.sum", "Makefile", "package.json", 
            "package-lock.json", "requirements.txt", "pyproject.toml", "poetry.lock"
        ]
        self.github_files = [".github", ".gitignore", "LICENSE", "README", ".gitattributes"]

    def is_binary(self, file_content: bytes) -> bool:
        """Vérifie si le contenu du fichier est probablement binaire."""
        # Vérifier les octets nuls et le ratio de caractères non imprimables
        text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
        return bool(file_content.translate(None, text_chars))

    def is_excluded_file_type(self, file_path: str) -> bool:
        """Vérifie si le type de fichier doit être exclu."""
        excluded_extensions = ['.md', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.pdf', 
                              '.zip', '.tar', '.gz', '.jar', '.class', '.exe', '.dll', '.so']
        
        # Vérifier l'extension
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Filtrer par langage si spécifié
        if self.lang_filter and self.lang_filter != '*':
            if file_ext != f'.{self.lang_filter}':
                return True
                
        return file_ext in excluded_extensions

    def is_likely_useful_file(self, file_path: str) -> bool:
        """Détermine si le fichier est susceptible d'être utile."""
        # Ignorer les fichiers cachés
        if any(part.startswith('.') for part in file_path.split('/')):
            return False
            
        # Ignorer les fichiers de test
        if 'test' in file_path.lower():
            return False
            
        # Vérifier les répertoires exclus
        for excluded_dir in self.excluded_dirs:
            if f"/{excluded_dir}/" in file_path or file_path.startswith(f"{excluded_dir}/"):
                return False
                
        # Vérifier les fichiers utilitaires ou de configuration
        for file_name in self.excluded_files:
            if file_name in file_path:
                return False
                
        # Vérifier les fichiers GitHub ou documentation
        for doc_file in self.github_files:
            if doc_file in file_path:
                return False
                
        # Vérifier les patterns exclus supplémentaires
        for pattern in self.exclude_patterns:
            if re.search(pattern, file_path):
                return False
                
        return True

    def has_sufficient_content(self, file_content: str) -> bool:
        """Vérifie si le fichier a un nombre minimum de lignes substantielles."""
        # Ignorer les commentaires et les lignes vides
        lines = [line for line in file_content.split('\n') 
                if line.strip() and not line.strip().startswith(('#', '//', '/*', '*', '<!--'))]
        return len(lines) >= self.min_line_count

    def download_repo(self) -> List[Tuple[str, str]]:
        """Télécharge et traite les fichiers d'un dépôt GitHub."""
        logger.info(f"Téléchargement du dépôt: {self.repo_url}, branche/tag: {self.branch_or_tag}")
        
        # Construire l'URL de téléchargement
        download_url = f"{self.repo_url}/archive/refs/heads/{self.branch_or_tag}.zip"
        if 'github.com' not in self.repo_url:
            logger.warning("L'URL ne semble pas être un dépôt GitHub valide")
            
        try:
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()  # Lever une exception pour les codes d'erreur HTTP
        except requests.exceptions.RequestException as e:
            logger.error(f"Échec du téléchargement: {e}")
            # Essayer avec le format tag si la branche a échoué
            alternate_url = f"{self.repo_url}/archive/refs/tags/{self.branch_or_tag}.zip"
            try:
                logger.info(f"Tentative avec l'URL de tag: {alternate_url}")
                response = requests.get(alternate_url, timeout=30)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                logger.error(f"Échec du téléchargement du tag: {e}")
                sys.exit(1)

        content = []
        try:
            zip_file = zipfile.ZipFile(io.BytesIO(response.content))
            
            # Filtrer les fichiers utiles
            total_files = len(zip_file.namelist())
            logger.info(f"Traitement de {total_files} fichiers...")
            
            for file_path in zip_file.namelist():
                # Ignorer les répertoires et les fichiers exclus
                if (file_path.endswith("/") or 
                    not self.is_likely_useful_file(file_path) or 
                    self.is_excluded_file_type(file_path)):
                    continue
                    
                file_content = zip_file.read(file_path)
                
                # Ignorer les fichiers binaires
                if self.is_binary(file_content):
                    continue
                    
                # Décoder le contenu du fichier
                try:
                    file_content_text = file_content.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        # Essayer avec une autre encodage
                        file_content_text = file_content.decode("latin-1")
                    except Exception:
                        logger.warning(f"Impossible de décoder: {file_path}")
                        continue
                        
                # Vérifier le contenu minimum
                if self.has_sufficient_content(file_content_text):
                    # Extraire le nom de fichier sans le préfixe du dépôt
                    parts = file_path.split('/', 1)
                    if len(parts) > 1:
                        relative_path = parts[1]
                    else:
                        relative_path = file_path
                    content.append((relative_path, file_content_text))
                
            logger.info(f"{len(content)} fichiers utiles trouvés")
            
        except zipfile.BadZipFile:
            logger.error("Le fichier téléchargé n'est pas un ZIP valide")
            sys.exit(1)
            
        return content

    def create_pdf(self, content: List[Tuple[str, str]]) -> None:
        """Crée un fichier PDF à partir du contenu des fichiers."""
        logger.info(f"Création du PDF: {self.output_file}")
        
        # Trier les fichiers par chemin
        content.sort(key=lambda x: x[0])
        
        # Configurer les styles
        styles = getSampleStyleSheet()
        
        # Style pour le titre du fichier
        title_style = ParagraphStyle(
            'FileTitle',
            parent=styles['Heading2'],
            fontSize=12,
            spaceAfter=6
        )
        
        # Style pour le code
        code_style = ParagraphStyle(
            'CodeBlock',
            parent=styles['Code'],
            fontSize=8,
            leftIndent=5,
            rightIndent=5,
            spaceAfter=6,
            fontName='Courier'
        )
        
        # Créer le document
        doc = SimpleDocTemplate(
            self.output_file, 
            pagesize=self.page_size,
            topMargin=0.5*inch, 
            bottomMargin=0.5*inch,
            leftMargin=0.5*inch,
            rightMargin=0.5*inch
        )
        
        story = []
        
        # Ajouter une page de titre
        title = Paragraph(f"Code Source: {self.repo_name}", styles['Title'])
        subtitle = Paragraph(f"Branche/Tag: {self.branch_or_tag}", styles['Heading2'])
        story.append(title)
        story.append(Spacer(1, 12))
        story.append(subtitle)
        story.append(Spacer(1, 36))
        
        # Ajouter la table des matières
        toc_title = Paragraph("Table des Matières", styles['Heading1'])
        story.append(toc_title)
        story.append(Spacer(1, 12))
        
        for i, (file_path, _) in enumerate(content):
            file_entry = Paragraph(f"{i+1}. {file_path}", styles['Normal'])
            story.append(file_entry)
            story.append(Spacer(1, 6))
            
        story.append(PageBreak())
        
        # Ajouter chaque fichier
        for file_path, file_content in content:
            # Tronquer les fichiers trop longs
            if len(file_content) > 100000:
                file_content = file_content[:100000] + "\n...[Contenu tronqué car trop volumineux]..."
                
            # Ajouter le titre du fichier
            story.append(Paragraph(f"Fichier: {file_path}", title_style))
            story.append(Spacer(1, 6))
            
            # Ajouter le contenu du fichier
            story.append(Preformatted(file_content, code_style))
            story.append(Spacer(1, 12))
            story.append(PageBreak())
            
        try:
            doc.build(story)
            logger.info(f"PDF créé avec succès: {self.output_file}")
        except Exception as e:
            logger.error(f"Erreur lors de la création du PDF: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description='Télécharge et convertit un dépôt GitHub en PDF',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('repo_url', type=str, help='URL du dépôt GitHub')
    parser.add_argument('--branch_or_tag', type=str, default="main", 
                        help='Branche ou tag du dépôt à télécharger')
    parser.add_argument('--output', type=str, help='Nom du fichier PDF de sortie')
    parser.add_argument('--page_size', type=str, choices=['A4', 'letter'], default='A4',
                        help='Taille du papier pour le PDF')
    parser.add_argument('--min_lines', type=int, default=5,
                        help='Nombre minimum de lignes pour inclure un fichier')
    parser.add_argument('--lang', type=str, 
                        help='Filtrer par langage (extension de fichier, ex: py pour Python)')
    parser.add_argument('--exclude', type=str, nargs='+', default=[],
                        help='Patterns regex additionnels à exclure')
    parser.add_argument('--verbose', action='store_true', 
                        help='Activer les messages de débogage détaillés')
    
    args = parser.parse_args()
    
    # Configurer le niveau de logging
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Créer le convertisseur
    converter = GithubToPDF(
        repo_url=args.repo_url,
        branch_or_tag=args.branch_or_tag,
        output_file=args.output,
        page_size=args.page_size,
        min_line_count=args.min_lines,
        lang_filter=args.lang,
        exclude_patterns=args.exclude
    )
    
    # Télécharger et convertir
    content = converter.download_repo()
    if content:
        converter.create_pdf(content)
    else:
        logger.error("Aucun fichier exploitable trouvé dans le dépôt")
        sys.exit(1)

if __name__ == "__main__":
    main()
