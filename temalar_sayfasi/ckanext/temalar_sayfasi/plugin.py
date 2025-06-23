# -*- coding: utf-8 -*-
"""
ckanext-temalar_sayfasi.plugin

Tema (category) yönetimi:
  • /temalar                – tema listesi (HERKES TÜM TEMALARI GÖRÜR)
  • /temalar/yeni           – yeni tema oluştur
  • /temalar/<slug>         – tema detay + veri setleri
  • /temalar/<slug>/edit    – düzenle
  • /temalar/<slug>/delete  – sil
  • /dashboard/temalar      – KULLANICIYA ÖZEL TEMA LİSTESİ (YENİ)
"""

import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import asbool
from flask import Blueprint

# Yeni eklenen modüller
from ckan.logic import NotAuthorized # Yetkilendirme için
import ckan.model as model # Kullanıcı modeline erişim için

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Yardımcı: CKAN config'ten varsayılan sonuç adedi
# ----------------------------------------------------------------------
ITEMS_PER_PAGE = int(tk.config.get('ckan.search.results_per_page', 20))


# ----------------------------------------------------------------------
# Görünümler
# ----------------------------------------------------------------------

def index():
    """Genel Tema listesi. Herkes tüm temaları görür. Yeni Tema Ekle butonu burada görünmez."""
    tk.c.is_dashboard = False
    tk.c.is_sysadmin = False
    tk.c.themes = []
    return tk.render('theme/index.html')

def dashboard_themes():
    """
    Kullanıcıya özel tema listesi.
    Sysadmin: Tüm temaları görür.
    Diğerleri: Sadece atandığı temaları görür.
    'Yeni Tema Ekle' butonu sadece sysadmin'lere görünür.
    """
    context = {'user': tk.c.user, 'ignore_auth': False}
    
    if not tk.c.user:
        tk.h.flash_error(tk._('Bu sayfayı görüntülemek için giriş yapmalısınız.'))
        return tk.h.redirect_to('/')

    try:
        is_sysadmin = tk.c.userobj and tk.c.userobj.sysadmin 
        
        tk.c.is_dashboard = True
        tk.c.is_sysadmin = is_sysadmin
        
        if is_sysadmin:
            themes = tk.get_action('theme_category_list')(context, {})
        else:
            user_id = tk.c.userobj.id
            
            user_assigned_themes_data = tk.get_action('get_user_themes')(context, {'user_id': user_id})
            
            themes = []
            for assignment in user_assigned_themes_data:
                try:
                    theme_detail = tk.get_action('theme_category_show')(context, {'slug': assignment['theme_slug']})
                    
                    if theme_detail and theme_detail.get('category'):
                        normalized_theme = theme_detail['category']
                        normalized_theme['dataset_count'] = len(theme_detail.get('datasets', []))
                        themes.append(normalized_theme)
                except tk.ObjectNotFound:
                    log.warning(f"Dashboard için tema bulunamadı: {assignment['theme_slug']}")
                    continue
                except Exception as e:
                    log.error(f"Dashboard için tema detayları yüklenirken hata: {assignment['theme_slug']} - {e}")
                    continue
        
        tk.c.themes = themes

    except NotAuthorized as e:
        tk.h.flash_error(tk._(str(e)))
        return tk.h.redirect_to('/') 
    except Exception as e:
        log.error("Dashboard temaları yüklenirken genel hata: %s", e, exc_info=True)
        tk.h.flash_error(tk._(f'Temaları yüklenirken beklenmeyen bir hata oluştu: {e}'))
        tk.abort(500, tk._('Temaları yüklenirken beklenmeyen bir hata oluştu.'))

    return tk.render('theme/index.html')


def new_theme():
    """Yeni tema oluştur (GET/POST). Yalnızca sysadmin erişebilir."""
    context = {'user': tk.c.user, 'ignore_auth': False}
    tk.check_access('sysadmin', context)
    
    tk.c.errors, tk.c.data = {}, {}

    if tk.request.method == 'POST':
        data_dict = {
            'slug':        tk.request.form.get('slug'),
            'name':        tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':       tk.request.form.get('color'),
            'icon':        tk.request.form.get('icon'),
        }
        try:
            tk.get_action('theme_category_create')(context, data_dict)
            tk.h.flash_success(tk._('Tema başarıyla oluşturuldu.'))
            return tk.h.redirect_to('temalar_sayfasi.dashboard_index')
        except tk.ValidationError as e:
            tk.c.errors, tk.c.data = e.error_dict, data_dict

    return tk.render('theme/new_theme.html')


def read_theme(slug):
    """
    /temalar/<slug> – Tema detayları. Herkesin erişebildiği detay sayfası.
    """
    try:
        log.info("Tema okuma isteği: %s", slug)

        context    = {'user': tk.c.user, 'ignore_auth': True}
        theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})
        tk.c.theme_data = theme_data

        dataset_ids = [ds['id'] for ds in theme_data.get('datasets', [])]

        packages, total = [], 0
        if dataset_ids:
            fq = "id:({})".format(" OR id:".join(dataset_ids))
            res = tk.get_action('package_search')(context, {
                'fq':              fq,
                'rows':            ITEMS_PER_PAGE,
                'include_private': True,
                'start':           (tk.request.args.get('page', 1) - 1) * ITEMS_PER_PAGE
            })
            packages, total = res['results'], res['count']

        class Page:
            def __init__(self, items, item_count):
                self.items          = items
                self.item_count     = item_count
                self.q              = tk.request.args.get('q', '')
                self.sort_by_selected = tk.request.args.get('sort', '')

                def _pager(**kw):
                    page = int(tk.request.args.get('page', 1))
                    url_params = {'q': self.q, 'sort': self.sort_by_selected}
                    return tk.h.pager(kw.get('base_url', tk.url_for('temalar_sayfasi.read', slug=slug)), 
                                      self.item_count, ITEMS_PER_PAGE, current_page=page, url_params=url_params)


                self.pager = _pager if self.item_count > ITEMS_PER_PAGE \
                             else (lambda **kw: '')

        tk.c.page = Page(packages, total)

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

        return tk.render('theme/theme_read.html')

    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        log.error("Tema yüklenirken hata: %s", e, exc_info=True)
        tk.h.flash_error(tk._(f'Tema yüklenirken bir hata oluştu: {e}'))
        tk.abort(500, tk._('Tema yüklenirken beklenmeyen bir hata oluştu.'))


def edit_theme(slug):
    """Tema bilgilerini ve dataset atamalarını düzenler."""
    context = {'user': tk.c.user, 'ignore_auth': False}

    # Kullanıcının sysadmin olup olmadığını kontrol et
    is_sysadmin = tk.check_access('sysadmin', context)
    
    # Kullanıcının bu temadaki rolünü belirle
    # Varsayılan olarak None, yetkisiz veya atanmamışsa
    tk.c.user_theme_role_for_this_theme = None 
    is_theme_authorized_for_edit = False

    if is_sysadmin:
        tk.c.user_theme_role_for_this_theme = 'admin' # Sysadmin ise 'admin' gibi davran
        is_theme_authorized_for_edit = True
    elif tk.c.userobj: # Sadece giriş yapmış kullanıcılar için tema rolünü kontrol et
        user_id = tk.c.userobj.id
        user_themes = tk.get_action('get_user_themes')(context, {'user_id': user_id})
        current_user_assignment = next((t for t in user_themes if t['theme_slug'] == slug), None)
        
        if current_user_assignment:
            assigned_role = current_user_assignment['role']
            tk.c.user_theme_role_for_this_theme = assigned_role
            if assigned_role in ['admin', 'editor']: # Editörler ve adminler erişebilir
                is_theme_authorized_for_edit = True

    # Eğer kullanıcı tema için düzenleme yetkisine sahip değilse (sysadmin veya atanmış admin/editör değilse)
    if not is_theme_authorized_for_edit:
        raise NotAuthorized(_('Bu temayı düzenlemek için yetkiniz yok.'))


    if tk.request.method == 'GET':
        tk.c.data, tk.c.errors = {}, {}

    if tk.request.method == 'POST':
        try:
            # 1) Bilgileri güncelle
            update_data = {
                'slug':        slug,
                'name':        tk.request.form.get('name'),
                'description': tk.request.form.get('description'),
                'color':       tk.request.form.get('color'),
                'icon':        tk.request.form.get('icon'),
            }
            tk.get_action('theme_category_update')(context, update_data)

            # 2) Dataset atamalarını güncelle
            new_ids = set(tk.request.form.getlist('dataset_ids'))
            current = tk.get_action('theme_category_show')(context, {'slug': slug})
            old_ids = set(ds['id'] for ds in current.get('datasets', []))

            for ds_id in new_ids - old_ids:
                tk.get_action('assign_dataset_theme')(context, {
                    'dataset_id': ds_id, 'theme_slug': slug
                })
            for ds_id in old_ids - new_ids:
                tk.get_action('remove_dataset_theme')(context, {
                    'dataset_id': ds_id
                })

            tk.h.flash_success(tk._('Tema başarıyla güncellendi.'))
            return tk.h.redirect_to('temalar_sayfasi.read', slug=slug)

        except tk.ValidationError as e:
            tk.c.errors, tk.c.data = e.error_dict, tk.request.form
            tk.h.flash_error(str(e))
        except Exception as e:
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form

    try:
        # theme_data'yı doğru şekilde al
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
    """Tema sil (yalnızca POST)."""
    if tk.request.method != 'POST':
        tk.abort(405, tk._('Bu sayfaya sadece POST metodu ile erişilebilir'))

    context = {'user': tk.c.user, 'ignore_auth': False} # Yetki kontrolü için ignore_auth False olmalı
    
    # Yetki kontrolü: Sadece sysadmin veya tema yöneticileri silebilir
    is_sysadmin = tk.check_access('sysadmin', context)
    if not is_sysadmin:
        if not tk.c.userobj: # Eğer giriş yapmamışsa
            raise NotAuthorized('Bu temayı silmek için yetkiniz yok.')

        user_id = tk.c.userobj.id
        user_themes = tk.get_action('get_user_themes')(context, {'user_id': user_id})
        is_theme_admin = any(t['theme_slug'] == slug and t['role'] == 'admin' for t in user_themes)
        
        if not is_theme_admin:
            raise NotAuthorized('Bu temayı silmek için yetkiniz yok.')


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

    # templates/ klasörünü sisteme tanıt
    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    def get_blueprint(self):
        bp = Blueprint('temalar_sayfasi', __name__)

        # Mevcut Tema Listesi (Herkes tümünü görür, Yeni Tema Ekle butonu burada GÖRÜNMEZ)
        bp.add_url_rule('/temalar', endpoint='index', view_func=index)
        
        # Yeni Tema Oluştur (Sadece sysadminler erişebilir)
        bp.add_url_rule('/temalar/yeni', endpoint='new', view_func=new_theme, methods=['GET', 'POST'])
        
        # Tema Detayları
        bp.add_url_rule('/temalar/<slug>', endpoint='read', view_func=read_theme)
        
        # Tema Düzenle (Sysadmin veya tema adminleri)
        bp.add_url_rule('/temalar/<slug>/edit', endpoint='edit', view_func=edit_theme, methods=['GET', 'POST'])
        
        # Tema Sil (Sysadmin veya tema adminleri)
        bp.add_url_rule('/temalar/<slug>/delete', endpoint='delete', view_func=delete_theme, methods=['POST'])

        # YENİ EKLENEN: Dashboard Tema Listesi (Kullanıcıya özel, sadece giriş yapmış, Yeni Tema Ekle butonu sadece sysadmin'e görünür)
        bp.add_url_rule('/dashboard/temalar', endpoint='dashboard_index', view_func=dashboard_themes) 

        return bp