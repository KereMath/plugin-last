import ckan.plugins as p
import ckan.plugins.toolkit as tk
from flask import Blueprint
import os
import ckan.lib.app_globals as app_globals 
import logging
import traceback
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
        log.info(f"Tema okuma isteği alındı: {slug}")

        context = {'user': tk.c.user, 'ignore_auth': True} 
        theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})
        tk.c.theme_data = theme_data 
        log.info(f"Tema verisi başarıyla çekildi: {theme_data.get('category', {}).get('name')}")

        dataset_ids_for_theme = [ds['id'] for ds in theme_data.get('datasets', [])]
        log.info(f"Temaya atanmış veri seti ID'leri: {dataset_ids_for_theme}")

        packages_list = []
        package_count = 0
        if dataset_ids_for_theme:
            fq_query = "id:({})".format(" OR id:".join(dataset_ids_for_theme))
            
            search_results = tk.get_action('package_search')(context, {
                'fq': fq_query,
                'rows': 1000, 
                'include_private': True 
            })
            packages_list = search_results.get('results', [])
            package_count = search_results.get('count', 0)
            log.info(f"package_search ile çekilen veri seti sayısı: {package_count}")
        else:
            log.info("Temaya atanmış veri seti bulunamadı, package_search çağrılmadı.")

        class Page:
            def __init__(self, items, item_count):
                self.items = items
                self.item_count = item_count
                self.q = tk.request.args.get('q', '')
                self.sort_by_selected = tk.request.args.get('sort', '')
                self.pager = lambda current_q: tk.h.pager(current_q, self.item_count, tk.c.items_per_page or 20) if self.item_count > (tk.c.items_per_page or 20) else ''

        tk.c.page = Page(packages_list, package_count)
        
        tk.c.q = tk.request.args.get('q', '')
        tk.c.sort_by_selected = tk.request.args.get('sort', '')
        tk.c.sort_by_options = [
            (tk._('Relevance'), 'score desc, metadata_modified desc'),
            (tk._('Name Ascending'), 'title_string asc'),
            (tk._('Name Descending'), 'title_string desc'),
            (tk._('Last Modified'), 'metadata_modified desc'),
            # HATA VEREN SATIR BURASIYDI: tk.app_globals yerine CKAN'da doğru erişim tk.g veya direkt import edilen app_globals
            (tk._('Popular'), 'views_recent desc') if app_globals.tracking_enabled else (False, False) # BURASI DÜZELTİLDİ
        ]
        tk.c.search_facets = {} 

        log.info("Şablon render ediliyor...")
        return tk.render('theme/theme_read.html')
    except tk.ObjectNotFound:
        log.warning(f"Tema bulunamadı: {slug}")
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        log.error(f"Tema yüklenirken beklenmeyen bir hata oluştu: {e}", exc_info=True)
        tk.h.flash_error(tk._(f'Tema yüklenirken bir hata oluştu: {e}'))
        tk.abort(500, tk._('Tema yüklenirken beklenmeyen bir hata oluştu.'))

# --- DÜZELTİLMİŞ FONKSİYON: TEMA DÜZENLEME ---
def edit_theme(slug):
    """
    Tema bilgilerini düzenler ve veri setlerini atar/kaldırır.
    """
    context = {'user': tk.c.user or tk.c.auth_user_obj.name}

    # Hata durumunda formu yeniden doldurmak için c.data ve c.errors'u hazırla
    if tk.request.method == 'GET':
        tk.c.data = {}
        tk.c.errors = {}

    if tk.request.method == 'POST':
        try:
            # 1. Tema bilgilerini güncelle
            update_data = {
                'slug': slug,
                'name': tk.request.form.get('name'),
                'description': tk.request.form.get('description'),
                'color': tk.request.form.get('color'),
                'icon': tk.request.form.get('icon'),
            }
            tk.get_action('theme_category_update')(context, update_data)

            # 2. Veri seti atamalarını yönet
            assigned_dataset_ids = tk.request.form.getlist('dataset_ids')
            
            # Mevcut atanmış veri setlerini al
            theme_details_for_post = tk.get_action('theme_category_show')(context, {'slug': slug})
            original_dataset_ids = [ds['id'] for ds in theme_details_for_post.get('datasets', [])]
            
            to_add = set(assigned_dataset_ids) - set(original_dataset_ids)
            to_remove = set(original_dataset_ids) - set(assigned_dataset_ids)

            for dataset_id in to_add:
                tk.get_action('assign_dataset_theme')(context, {'dataset_id': dataset_id, 'theme_slug': slug})

            for dataset_id in to_remove:
                tk.get_action('remove_dataset_theme')(context, {'dataset_id': dataset_id})

            tk.h.flash_success(tk._('Tema başarıyla güncellendi.'))
            return tk.h.redirect_to('temalar_sayfasi.read', slug=slug)

        except tk.ValidationError as e:
            tk.h.flash_error(str(e))
            tk.c.errors = e.error_dict
            tk.c.data = tk.request.form
        except Exception as e:
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form

    # GET isteği veya POST'ta hata olması durumunda sayfa render edilir
    try:
        # Tema detaylarını al
        theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
        tk.c.theme_data = theme_data
        
        # Tüm veri setlerini al
        all_datasets = tk.get_action('package_search')(context, {'rows': 1000, 'include_private': True})
        tk.c.all_datasets = all_datasets['results']
        
        return tk.render('theme/edit_theme.html')
    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        tk.abort(500, tk._(f"Sayfa yüklenirken bir hata oluştu: {e}"))


# --- YENİ EKLENEN FONKSİYON: TEMA SİLME ---
def delete_theme(slug):
    """
    Temayı siler.
    """
    context = {'user': tk.c.user or tk.c.auth_user_obj.name}
    
    if tk.request.method == 'POST':
        try:
            tk.get_action('theme_category_delete')(context, {'slug': slug})
            tk.h.flash_success(tk._('Tema başarıyla silindi.'))
            return tk.h.redirect_to('temalar_sayfasi.index')
        except tk.ValidationError as e:
            tk.h.flash_error(str(e))
            return tk.h.redirect_to('temalar_sayfasi.edit', slug=slug)
        except Exception as e:
            tk.h.flash_error(tk._(f'Tema silinirken bir hata oluştu: {e}'))
            return tk.h.redirect_to('temalar_sayfasi.edit', slug=slug)
    
    # GET isteği ile direkt erişimi engelle
    tk.abort(405, tk._('Bu sayfaya sadece POST metodu ile erişilebilir'))


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
        blueprint.add_url_rule('/temalar/<slug>/edit', endpoint='edit', view_func=edit_theme, methods=['GET', 'POST'])
        blueprint.add_url_rule('/temalar/<slug>/delete', endpoint='delete', view_func=delete_theme, methods=['POST'])

        return blueprint