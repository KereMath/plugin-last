import ckan.plugins as p
import ckan.plugins.toolkit as tk
from flask import Blueprint
import os

# Bu fonksiyonlar aynı kalıyor
def index():
    return tk.render('theme/index.html')

def new_theme():
    tk.c.errors = {}
    tk.c.data = {}
    if tk.request.method == 'POST':
        data_dict = {
            'slug': tk.request.form.get('slug'),
            'name': tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color': tk.request.form.get('color'),
            'icon': tk.request.form.get('icon'),
        }
        try:
            tk.get_action('theme_category_create')({}, data_dict)
            tk.h.flash_success(tk._('Tema başarıyla oluşturuldu.'))
            return tk.h.redirect_to('temalar_sayfasi.index')
        except tk.ValidationError as e:
            tk.c.errors = e.error_dict
            tk.c.data = data_dict
    return tk.render('theme/new_theme.html')

# --- YENİ EKLENEN FONKSİYON ---
# Tema detay sayfasını yönetir. URL'den slug'ı parametre olarak alır.
def read_theme(slug):
    try:
        # Senin sağladığın 'theme_category_show' API'sini çağırırız
        theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
        # Gelen veriyi şablonda kullanmak için tk.c'ye atarız
        tk.c.theme_data = theme_data
        return tk.render('theme/theme_read.html')
    except tk.ObjectNotFound:
        # Eğer o slug ile bir tema bulunamazsa 404 hatası göster
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        # Başka bir hata olursa 500 hatası göster
        tk.abort(500, tk._(f'Tema yüklenirken bir hata oluştu: {e}'))


class TemalarSayfasiPlugin(p.SingletonPlugin):
    p.implements(p.IBlueprint)
    p.implements(p.IConfigurer)  # Bu interface'i ekliyoruz

    # Template dizinini CKAN'a kaydetmek için
    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    def get_blueprint(self):
        # Template folder parametresini kaldırıyoruz
        blueprint = Blueprint('temalar_sayfasi', self.__module__)

        # Rotalarımız
        blueprint.add_url_rule('/temalar', endpoint='index', view_func=index)
        blueprint.add_url_rule('/temalar/yeni', endpoint='new', view_func=new_theme, methods=['GET', 'POST'])

        # --- YENİ EKLENEN ROTA ---
        # /temalar/ekonomi gibi dinamik URL'leri yakalar
        blueprint.add_url_rule('/temalar/<slug>', endpoint='read', view_func=read_theme)

        return blueprint