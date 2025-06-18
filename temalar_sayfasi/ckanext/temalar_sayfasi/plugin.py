# -*- coding: utf-8 -*-
"""
ckanext-temalar_sayfasi.plugin

Tema (category) yönetimi:
  * /temalar           – tema listesi (index)
  * /temalar/yeni      – yeni tema oluştur
  * /temalar/<slug>    – tema detayları + veri setleri
  * /temalar/<slug>/edit
  * /temalar/<slug>/delete
"""

import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import asbool
from flask import Blueprint

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Görünümler
# ----------------------------------------------------------------------

def index():
    """Tema listesi."""
    return tk.render('theme/index.html')


def new_theme():
    """Yeni tema oluşturma formu (GET/POST)."""
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


def read_theme(slug):
    """
    /temalar/<slug>  –  Tema detayları ve ona bağlı veri setleri.
    """
    try:
        log.info("Tema okuma isteği alındı: %s", slug)

        context    = {'user': tk.c.user, 'ignore_auth': True}
        theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})
        tk.c.theme_data = theme_data
        log.info("Tema verisi çekildi: %s", theme_data.get('category', {}).get('name'))

        dataset_ids = [ds['id'] for ds in theme_data.get('datasets', [])]
        log.info("Temaya atanmış dataset ID'leri: %s", dataset_ids)

        packages, total = [], 0
        if dataset_ids:
            fq = "id:({})".format(" OR id:".join(dataset_ids))
            res = tk.get_action('package_search')(context, {
                'fq':              fq,
                'rows':            1000,
                'include_private': True,
            })
            packages = res['results']
            total    = res['count']
            log.info("package_search sonuç sayısı: %s", total)

        # CKAN config'teki sonuç sayısı (varsayılan 20)
        ipp = int(tk.config.get('ckan.search.results_per_page', 20))

        class Page:
            def __init__(self, items, item_count):
                self.items              = items
                self.item_count         = item_count
                self.q                  = tk.request.args.get('q', '')
                self.sort_by_selected   = tk.request.args.get('sort', '')
                self.pager = (
                    lambda current_q: tk.h.pager(current_q, self.item_count, ipp)
                    if self.item_count > ipp else ''
                )

        tk.c.page = Page(packages, total)

        # Sıralama menüsü
        tracking_enabled = asbool(tk.config.get('ckan.tracking_enabled', False))
        tk.c.sort_by_options = [
            (tk._('Relevance'),        'score desc, metadata_modified desc'),
            (tk._('Name Ascending'),   'title_string asc'),
            (tk._('Name Descending'),  'title_string desc'),
            (tk._('Last Modified'),    'metadata_modified desc'),
        ]
        if tracking_enabled:
            tk.c.sort_by_options.append((tk._('Popular'), 'views_recent desc'))

        tk.c.q = tk.request.args.get('q', '')
        tk.c.sort_by_selected = tk.request.args.get('sort', '')
        tk.c.search_facets = {}

        log.info("Şablon render ediliyor…")
        return tk.render('theme/theme_read.html')

    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        log.error("Tema yüklenirken hata: %s", e, exc_info=True)
        tk.h.flash_error(tk._(f'Tema yüklenirken bir hata oluştu: {e}'))
        tk.abort(500, tk._('Tema yüklenirken beklenmeyen bir hata oluştu.'))


def edit_theme(slug):
    """
    Tema bilgilerini ve dataset atamalarını düzenler (GET/POST).
    """
    context = {'user': tk.c.user or tk.c.auth_user_obj.name}

    if tk.request.method == 'GET':
        tk.c.data   = {}
        tk.c.errors = {}

    if tk.request.method == 'POST':
        try:
            # Bilgileri güncelle
            update_data = {
                'slug':        slug,
                'name':        tk.request.form.get('name'),
                'description': tk.request.form.get('description'),
                'color':       tk.request.form.get('color'),
                'icon':        tk.request.form.get('icon'),
            }
            tk.get_action('theme_category_update')(context, update_data)

            # Dataset atamalarını güncelle
            new_ids = set(tk.request.form.getlist('dataset_ids'))
            current = tk.get_action('theme_category_show')(context, {'slug': slug})
            old_ids = set(ds['id'] for ds in current.get('datasets', []))

            for ds_id in new_ids - old_ids:
                tk.get_action('assign_dataset_theme')(context, {
                    'dataset_id': ds_id,
                    'theme_slug': slug
                })

            for ds_id in old_ids - new_ids:
                tk.get_action('remove_dataset_theme')(context, {
                    'dataset_id': ds_id
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

    # Formu göster
    try:
        tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
        all_ds = tk.get_action('package_search')(context, {
            'rows':            1000,
            'include_private': True
        })
        tk.c.all_datasets = all_ds['results']
        return tk.render('theme/edit_theme.html')
    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        tk.abort(500, tk._(f"Sayfa yüklenirken bir hata oluştu: {e}"))


def delete_theme(slug):
    """
    Tema sil (yalnızca POST).
    """
    if tk.request.method != 'POST':
        tk.abort(405, tk._('Bu sayfaya sadece POST metodu ile erişilebilir'))

    context = {'user': tk.c.user or tk.c.auth_user_obj.name}

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
# CKAN Plugin tanımı
# ----------------------------------------------------------------------

class TemalarSayfasiPlugin(p.SingletonPlugin):
    p.implements(p.IBlueprint)
    p.implements(p.IConfigurer)

    # templates/ klasörünü kaydet
    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    def get_blueprint(self):
        bp = Blueprint('temalar_sayfasi', __name__)

        bp.add_url_rule('/temalar',              endpoint='index',
                        view_func=index)
        bp.add_url_rule('/temalar/yeni',         endpoint='new',
                        view_func=new_theme,    methods=['GET', 'POST'])
        bp.add_url_rule('/temalar/<slug>',       endpoint='read',
                        view_func=read_theme)
        bp.add_url_rule('/temalar/<slug>/edit',  endpoint='edit',
                        view_func=edit_theme,   methods=['GET', 'POST'])
        bp.add_url_rule('/temalar/<slug>/delete', endpoint='delete',
                        view_func=delete_theme, methods=['POST'])

        return bp
