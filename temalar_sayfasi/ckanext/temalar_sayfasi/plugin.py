# -*- coding: utf-8 -*-
"""
ckanext-temalar_sayfasi.plugin
Tüm “Tema” sayfalarını yöneten CKAN eklentisi
"""

import logging
import os

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import asbool   # tracking_enabled bayrağını config’ten okumak için
from flask import Blueprint

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Görünümler
# ----------------------------------------------------------------------

def index():
    """/temalar ana sayfası"""
    return tk.render('theme/index.html')


def new_theme():
    """Yeni tema oluşturma formu – GET/POST"""
    tk.c.errors = {}
    tk.c.data = {}

    if tk.request.method == 'POST':
        data_dict = {
            'slug':        tk.request.form.get('slug'),
            'name':        tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':       tk.request.form.get('color'),
            'icon':        tk.request.form.get('icon'),
        }
        try:
            tk.get_action('theme_category_create')({}, data_dict)
            tk.h.flash_success(tk._('Tema başarıyla oluşturuldu.'))
            return tk.h.redirect_to('temalar_sayfasi.index')
        except tk.ValidationError as e:
            tk.c.errors = e.error_dict
            tk.c.data   = data_dict

    return tk.render('theme/new_theme.html')


# ----------------------------------------------------------------------
# Tema detay sayfası
# ----------------------------------------------------------------------

def read_theme(slug):
    """
    /temalar/<slug>
    Bir temaya ait detaylar ve o temaya bağlı veri setleri
    """
    try:
        log.info(f"Tema okuma isteği alındı: {slug}")

        context     = {'user': tk.c.user, 'ignore_auth': True}
        theme_data  = tk.get_action('theme_category_show')(context, {'slug': slug})
        tk.c.theme_data = theme_data
        log.info(f"Tema verisi başarıyla çekildi: {theme_data.get('category', {}).get('name')}")

        # Temaya bağlı dataset ID’leri
        dataset_ids_for_theme = [ds['id'] for ds in theme_data.get('datasets', [])]
        log.info(f"Temaya atanmış veri seti ID'leri: {dataset_ids_for_theme}")

        # İlgili paketleri çek
        packages_list, package_count = [], 0
        if dataset_ids_for_theme:
            fq_query = "id:({})".format(" OR id:".join(dataset_ids_for_theme))
            search_results = tk.get_action('package_search')(context, {
                'fq':              fq_query,
                'rows':            1000,
                'include_private': True,
            })
            packages_list  = search_results.get('results', [])
            package_count  = search_results.get('count', 0)
            log.info(f"package_search ile çekilen veri seti sayısı: {package_count}")
        else:
            log.info("Temaya atanmış veri seti bulunamadı, package_search çağrılmadı.")

        # Pager/diziler için basit kapsayıcı sınıf
        class Page:
            def __init__(self, items, item_count):
                self.items   = items
                self.item_count = item_count
                self.q       = tk.request.args.get('q', '')
                self.sort_by_selected = tk.request.args.get('sort', '')
                # items_per_page CKAN config veya varsayılan 20
                ipp = tk.c.items_per_page or 20
                self.pager = (
                    lambda current_q: tk.h.pager(current_q, self.item_count, ipp)
                    if self.item_count > ipp else ''
                )

        tk.c.page = Page(packages_list, package_count)

        # Arama ve sıralama seçenekleri
        tk.c.q = tk.request.args.get('q', '')
        tk.c.sort_by_selected = tk.request.args.get('sort', '')

        # CKAN config’inden tracking’in açık olup olmadığını oku
        tracking_enabled = asbool(tk.config.get('ckan.tracking_enabled', False))

        tk.c.sort_by_options = [
            (tk._('Relevance'),        'score desc, metadata_modified desc'),
            (tk._('Name Ascending'),   'title_string asc'),
            (tk._('Name Descending'),  'title_string desc'),
            (tk._('Last Modified'),    'metadata_modified desc'),
        ]
        if tracking_enabled:
            tk.c.sort_by_options.append((tk._('Popular'), 'views_recent desc'))

        tk.c.search_facets = {}

        log.info("Şablon render ediliyor...")
        return tk.render('theme/theme_read.html')

    except tk.ObjectNotFound:
        log.warning(f"Tema bulunamadı: {slug}")
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        log.error(
            f"Tema yüklenirken beklenmeyen bir hata oluştu: {e}",
            exc_info=True
        )
        tk.h.flash_error(tk._(f'Tema yüklenirken bir hata oluştu: {e}'))
        tk.abort(500, tk._('Tema yüklenirken beklenmeyen bir hata oluştu.'))


# ----------------------------------------------------------------------
# Tema düzenleme sayfası
# ----------------------------------------------------------------------

def edit_theme(slug):
    """Tema bilgilerini ve dataset atamalarını düzenler"""
    context = {'user': tk.c.user or tk.c.auth_user_obj.name}

    # GET: formu temizle
    if tk.request.method == 'GET':
        tk.c.data   = {}
        tk.c.errors = {}

    if tk.request.method == 'POST':
        try:
            # 1) Tema bilgilerini güncelle
            update_data = {
                'slug':        slug,
                'name':        tk.request.form.get('name'),
                'description': tk.request.form.get('description'),
                'color':       tk.request.form.get('color'),
                'icon':        tk.request.form.get('icon'),
            }
            tk.get_action('theme_category_update')(context, update_data)

            # 2) Dataset atamalarını güncelle
            assigned_dataset_ids = tk.request.form.getlist('dataset_ids')

            theme_details_for_post = tk.get_action('theme_category_show')(context, {'slug': slug})
            original_dataset_ids = [ds['id'] for ds in theme_details_for_post.get('datasets', [])]

            to_add    = set(assigned_dataset_ids) - set(original_dataset_ids)
            to_remove = set(original_dataset_ids) - set(assigned_dataset_ids)

            for dataset_id in to_add:
                tk.get_action('assign_dataset_theme')(context, {
                    'dataset_id': dataset_id,
                    'theme_slug': slug
                })

            for dataset_id in to_remove:
                tk.get_action('remove_dataset_theme')(context, {
                    'dataset_id': dataset_id
                })

            tk.h.flash_success(tk._('Tema başarıyla güncellendi.'))
            return tk.h.redirect_to('temalar_sayfasi.read', slug=slug)

        except tk.ValidationError as e:
            tk.h.flash_error(str(e))
            tk.c.errors = e.error_dict
            tk.c.data   = tk.request.form
        except Exception as e:
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form

    # (GET) veya (POST hata) -> sayfayı yeniden göster
    try:
        tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})

        all_datasets = tk.get_action('package_search')(context, {
            'rows':            1000,
            'include_private': True
        })
        tk.c.all_datasets = all_datasets['results']

        return tk.render('theme/edit_theme.html')
    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        tk.abort(500, tk._(f"Sayfa yüklenirken bir hata oluştu: {e}"))


# ----------------------------------------------------------------------
# Tema silme
# ----------------------------------------------------------------------

def delete_theme(slug):
    """Tema silme işlemi – sadece POST"""
    context = {'user': tk.c.user or tk.c.auth_user_obj.name}

    if tk.request.method != 'POST':
        tk.abort(405, tk._('Bu sayfaya sadece POST metodu ile erişilebilir'))

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


# ----------------------------------------------------------------------
# CKAN Plugin
# ----------------------------------------------------------------------

class TemalarSayfasiPlugin(p.SingletonPlugin):
    """CKAN Plugin tanımı"""

    p.implements(p.IBlueprint)
    p.implements(p.IConfigurer)

    # Template dizinini CKAN’a tanıt
    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    # Blueprint ve rotalar
    def get_blueprint(self):
        blueprint = Blueprint('temalar_sayfasi', self.__module__)

        blueprint.add_url_rule('/temalar',          endpoint='index',  view_func=index)
        blueprint.add_url_rule('/temalar/yeni',     endpoint='new',    view_func=new_theme, methods=['GET', 'POST'])

        # Dinamik slug tabanlı rotalar
        blueprint.add_url_rule('/temalar/<slug>',            endpoint='read',   view_func=read_theme)
        blueprint.add_url_rule('/temalar/<slug>/edit',       endpoint='edit',   view_func=edit_theme,   methods=['GET', 'POST'])
        blueprint.add_url_rule('/temalar/<slug>/delete',     endpoint='delete', view_func=delete_theme, methods=['POST'])

        return blueprint
