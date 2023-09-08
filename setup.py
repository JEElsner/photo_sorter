from setuptools import setup, find_packages
import versioneer

setup(
    name="PhotoSorter",
    author="Jonathan Elsner",
    author_email="jeelsner@outlook.com",
    description="Sort photos into subfolders by year and month either on disk or on OneDrive using the Microsoft Graph API",
    packages=find_packages(),
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
)
