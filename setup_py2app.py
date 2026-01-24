from setuptools import setup, find_packages


APP = ["Transcendence.py"]
OPTIONS = {
    "argv_emulation": True,
    "packages": ["lib", "prompts", "rulesets"],
    "plist": {
        "CFBundleName": "Transcendence",
        "CFBundleDisplayName": "Transcendence",
        "CFBundleIdentifier": "com.transcendence.sim",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
    },
}


setup(
    name="Transcendence",
    app=APP,
    options={"py2app": OPTIONS},
    packages=find_packages(),
    package_data={
        "lib": ["events_catalog.json"],
        "prompts": ["*.py"],
        "rulesets": ["*.py"],
    },
)
