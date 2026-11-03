from setuptools import setup, find_packages

setup(
    name="opencivil",
    version="0.7",
    description="A parametric 3D structural analysis API and GUI",
    author="Shaikh Ahmed Azad",
    packages=find_packages(),
    install_requires=[
        "numpy",
        "scipy",
        "PyQt6", 
        "requests",
        "cryptography",
    ],
    entry_points={
        'console_scripts': [
            'opencivil=core.cli:start_terminal',
            'opencivil_gui=app.main:main',  
        ],
    },
)
