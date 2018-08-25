from distutils.core import setup

setup(
    name='locust-flying-locust_extension',
    version='0.0.1',
    packages=['locust_extension'],
    url='https://github.com/Vern1erCa11per/',
    license='MIT',
    author='vern1ercallper',
    author_email='26157023+Vern1erCa11per@users.noreply.github.com',
    description='locust_extension for performance testing framework Locust',
    entry_points={
        'console_scripts': [
            'locust-flying-extension = locust_extension.main:main',
        ]
    }
)
