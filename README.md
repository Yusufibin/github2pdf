[![License: MIT](https://img.shields.io/badge/License-APACHE-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/release/python-360/)

# Github2pdf

Github2pdf est un outil en ligne de commande qui permet de télécharger le contenu d'un dépôt GitHub et de le convertir en un fichier PDF unique. Cet outil est particulièrement utile pour les développeurs qui souhaitent avoir une vue d'ensemble de leur code source dans un format facilement partageable et imprimable.

## Caractéristiques

- Télécharge tous les fichiers non binaires d'un dépôt GitHub spécifié.
- Exclut automatiquement les fichiers Markdown (.md).
- Génère un PDF bien formaté avec le contenu de tous les fichiers.
- Prend en charge différentes branches ou tags du dépôt.
- Exclut les fichiers et répertoires couramment non pertinents (comme les tests, les exemples, etc.).
- Vérifie que les fichiers ont un contenu suffisant avant de les inclure.

## Prérequis

- Python 3.6 ou supérieur
- pip (gestionnaire de paquets Python)

## Installation

1. Clonez ce dépôt ou téléchargez le script `github2pdf.py`.

2. Installez les dépendances nécessaires :

```bash
pip install requests reportlab
```

## Utilisation

Pour utiliser Github2pdf, exécutez le script en ligne de commande avec l'URL du dépôt GitHub comme argument :

```bash
python github2pdf.py https://github.com/username/repo
```

### Options

- `--branch_or_tag` : Spécifie la branche ou le tag à télécharger (par défaut : "master")

Exemple :

```bash
python github2pdf.py https://github.com/username/repo --branch_or_tag develop
```

## Sortie

Le script générera un fichier PDF dans le répertoire courant. Le nom du fichier sera basé sur le nom du dépôt, par exemple : `repo_all_files.pdf`.

## Limitations

- Les fichiers binaires sont exclus du PDF généré.
- Les fichiers Markdown (.md) sont intentionnellement exclus.
- Les fichiers très volumineux peuvent ralentir le processus de génération du PDF ou entraîner des problèmes de mémoire.

## Contribution

Les contributions à ce projet sont les bienvenues ! N'hésitez pas à ouvrir une issue pour signaler un bug ou proposer une amélioration, ou à soumettre une pull request avec vos modifications.

## Licence

Ce projet est sous licence MIT. Voir le fichier `LICENSE` pour plus de détails.

---

Pour toute question ou problème, veuillez ouvrir une issue dans ce dépôt Github. 
