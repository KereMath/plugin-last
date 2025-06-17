from setuptools import setup, find_packages

setup(
    name='ckanext-temalarsayfasi',
    version='1.0',
    description='Temalar sayfasini CKANe ekleyen eklenti.',
    packages=find_packages(),
    # BU YENİ SATIRLAR EKLENDİ
    include_package_data=True,
    package_data={
        'ckanext.temalar_sayfasi': ['templates/*/*.html'],
    },
    # --
    entry_points="""
        [ckan.plugins]
        temalar_sayfasi=ckanext.temalar_sayfasi.plugin:TemalarSayfasiPlugin
    """,
    message_extractors={
        'ckanext': [
            ('**.py', 'python', None),
            ('**.js', 'javascript', None),
            ('**/templates/**.html', 'ckan', None),
        ],
    },
)