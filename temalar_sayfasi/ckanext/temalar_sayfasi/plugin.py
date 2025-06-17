import ckan.plugins as p
import ckan.plugins.toolkit as tk
from flask import Blueprint

def index():
    return tk.render('theme/index.html')

class TemalarSayfasiPlugin(p.SingletonPlugin):
    p.implements(p.IBlueprint)
    p.implements(p.IConfigurer)  # BU EKLENDİ

    # IConfigurer için gerekli
    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    # IBlueprint için gerekli
    def get_blueprint(self):
        blueprint = Blueprint(
            'temalar_sayfasi_blueprint',
            self.__module__,
            template_folder='templates'  # Bu satır da kalabilir
        )
        blueprint.add_url_rule('/temalar', view_func=index)
        return blueprint