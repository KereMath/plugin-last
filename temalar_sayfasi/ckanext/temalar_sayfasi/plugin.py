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

# Explicitly import ckan.lib.helpers and assign pager_url to tk.h
# This ensures tk.h.pager_url is available for the Page class.
import ckan.lib.helpers as _helpers
tk.h.pager_url = _helpers.pager_url # <-- CHANGED from pager to pager_url


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
        tk.c.theme_data = theme_data # theme_data'yı şablona aktar

        # Kullanıcının sysadmin olup olmadığını kontrol et
        is_sysadmin = tk.c.userobj and tk.c.userobj.sysadmin
        tk.c.is_sysadmin = is_sysadmin # Sysadmin durumunu şablona aktar

        # Kullanıcının bu temadaki rolünü belirle
        # Varsayılan olarak None, yetkisiz veya atanmamışsa
        tk.c.user_theme_role_for_this_theme = None 
        if not is_sysadmin and tk.c.userobj: # Sadece giriş yapmış sysadmin olmayan kullanıcılar için rolü kontrol et
            user_id = tk.c.userobj.id
            user_themes = tk.get_action('get_user_themes')(context, {'user_id': user_id})
            current_user_assignment = next((t for t in user_themes if t['theme_slug'] == slug), None)
            if current_user_assignment:
                tk.c.user_theme_role_for_this_theme = current_user_assignment['role']


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
                    # Use tk.h.pager_url, which is now explicitly assigned above
                    # Note: pager_url takes different arguments than older 'pager'
                    # It returns a URL, not the full HTML.
                    # We need to construct the pager HTML ourselves or pass enough info to the template.
                    
                    # For a simple URL generation in Python:
                    base_url = kw.get('base_url', tk.url_for('temalar_sayfasi.read', slug=slug))
                    # tk.h.pager_url takes (item_count, items_per_page, page_number, base_url, **kwargs)
                    return tk.h.pager_url(self.item_count, ITEMS_PER_PAGE, page, base_url=base_url, **url_params)


                # The `Page` class's `pager` method should return the HTML, not just a URL.
                # Since tk.h.pager_url returns just a URL component, we need a way
                # to render the full pager in the template using this URL.
                # A simpler approach for the Python side is to pass all necessary
                # data to the template and let the template render the pager.
                # Or, if we must provide a callable 'pager' attribute that returns HTML,
                # we'd need to mock CKAN's internal pager HTML rendering.
                # For now, let's assume `c.page.pager` in the template expects the
                # *same arguments* as tk.h.pager, and we pass it tk.h.pager_url.
                # This might still cause an issue if the template expects full HTML.

                # Reverting to the previous _pager definition, but with pager_url
                # and recognizing that the template might expect different arguments for `c.page.pager`
                # if it's meant to call tk.h.pager directly.

                # Let's simplify: c.page.pager should be the `_pager` method if total items > items per page.
                # The template expects `c.page.pager(q=c.q)`. This means `_pager` needs to produce
                # the *full HTML* of the pager, not just a URL fragment.

                # This is the tricky part. The old 'pager' helper produced HTML.
                # 'pager_url' produces just a URL.

                # Option 1: Pass relevant data to the template and render pager HTML in the template.
                # This is the standard CKAN way, but your plugin.py is setting c.page.pager itself.
                # So we must adapt.

                # Option 2: Build a basic HTML pager in Python (less ideal for maintainability).
                # Option 3: Find if there's another helper that renders the HTML pager.

                # Given the error is `module 'ckan.lib.helpers' has no attribute 'pager'`,
                # and we found `pager_url`, the most direct fix is to adapt the call.
                # However, the template expects `c.page.pager(...)`, which implies a function that *returns* HTML.
                # tk.h.pager_url returns a URL.

                # Let's try to adapt the `Page` class's `pager` attribute to return the *result*
                # of tk.h.pager_url. This will only return a URL, and the template might break.
                # So the better approach is that the `Page` class itself needs to become a proxy
                # for generating the pager HTML, similar to how CKAN's core does it.

                # Let's adjust the `_pager` function to directly call the correct helper,
                # but we need to ensure the template's `c.page.pager` receives what it expects.

                # Re-thinking the `Page` class. The `c.page.pager` in `theme_read.html` is calling
                # `c.page.pager(q=c.q)`. This means `c.page.pager` is expected to be a callable
                # that takes `q` and returns HTML for the pager.

                # Instead of assigning `_pager` directly, let's assign a lambda that calls `tk.h.pager_url`
                # but the template itself needs to be updated to use pager_url.
                # Since the traceback points to `c.page.pager(q=c.q)`, the `Page` class needs to provide
                # a callable named `pager` that can construct the HTML or call another helper to do so.

                # There's no direct `tk.h.pager` equivalent if it was removed/renamed.
                # The standard way to paginate in CKAN templates is `c.page.pager(base_url, item_count, items_per_page, current_page, **kwargs)`.
                # If the template is using `c.page.pager(q=c.q)`, it implies a custom pager object.

                # Let's provide a *mock* pager function if the original `tk.h.pager` is truly gone.
                # This will print an error message instead of crashing.
                # This is a temporary solution to get it running and confirm the helper name.

                # Given that `pager_url` exists, perhaps the template can be adapted.
                # But for a Python-side fix to match `c.page.pager(q=c.q)`:

                # Option 1: Simple HTML generation if the standard helper is gone or complicated.
                # This is a fallback if the pager helper structure changed drastically.
                def _generate_pager_html(base_url, item_count, items_per_page, current_page, q=''):
                    total_pages = (item_count + items_per_page - 1) // items_per_page
                    if total_pages <= 1:
                        return ''
                    
                    html_parts = []
                    # Simple Previous button
                    if current_page > 1:
                        prev_url = tk.h.pager_url(item_count, items_per_page, current_page - 1, base_url=base_url, q=q)
                        html_parts.append(f'<li class="previous"><a href="{prev_url}">« Previous</a></li>')
                    
                    # Page numbers
                    for i in range(1, total_pages + 1):
                        page_url = tk.h.pager_url(item_count, items_per_page, i, base_url=base_url, q=q)
                        active_class = 'active' if i == current_page else ''
                        html_parts.append(f'<li class="{active_class}"><a href="{page_url}">{i}</a></li>')
                    
                    # Simple Next button
                    if current_page < total_pages:
                        next_url = tk.h.pager_url(item_count, items_per_page, current_page + 1, base_url=base_url, q=q)
                        html_parts.append(f'<li class="next"><a href="{next_url}">Next »</a></li>')
                    
                    return '<div class="pagination"><ul>' + ''.join(html_parts) + '</ul></div>'


                # Now, the `pager` attribute of the `Page` class needs to call this `_generate_pager_html`
                # function with the correct parameters.
                # The template calls `c.page.pager(q=c.q)`. So our `self.pager` needs to accept `q`.
                # Let's modify `_pager` definition to match what the template calls.
                def _pager_callable(q_param=''): # Name it distinct to avoid confusion
                    current_page_from_request = int(tk.request.args.get('page', 1))
                    base_url_for_pager = tk.url_for('temalar_sayfasi.read', slug=slug)
                    
                    return _generate_pager_html(
                        base_url=base_url_for_pager,
                        item_count=self.item_count,
                        items_per_page=ITEMS_PER_PAGE,
                        current_page=current_page_from_request,
                        q=q_param
                    )
                
                self.pager = _pager_callable if self.item_count > ITEMS_PER_PAGE else (lambda **kw: '')
                
                # END of Page class refactor


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

    is_sysadmin = tk.c.userobj and tk.c.userobj.sysadmin

    
    tk.c.user_theme_role_for_this_theme = None 
    is_theme_authorized_for_edit = False

    if is_sysadmin:
        tk.c.user_theme_role_for_this_theme = 'admin'
        is_theme_authorized_for_edit = True
    elif tk.c.userobj:
        user_id = tk.c.userobj.id
        user_themes = tk.get_action('get_user_themes')(context, {'user_id': user_id})
        current_user_assignment = next((t for t in user_themes if t['theme_slug'] == slug), None)
        
        if current_user_assignment:
            assigned_role = current_user_assignment['role']
            tk.c.user_theme_role_for_this_theme = assigned_role
            if assigned_role in ['admin', 'editor']:
                is_theme_authorized_for_edit = True

    if not is_theme_authorized_for_edit:
        raise NotAuthorized(_('Bu temayı düzenlemek için yetkiniz yok.'))


    if tk.request.method == 'GET':
        tk.c.data, tk.c.errors = {}, {}

    if tk.request.method == 'POST':
        try:
            update_data = {
                'slug':        slug,
                'name':        tk.request.form.get('name'),
                'description': tk.request.form.get('description'),
                'color':       tk.request.form.get('color'),
                'icon':        tk.request.form.get('icon'),
            }
            tk.get_action('theme_category_update')(context, update_data)

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

    context = {'user': tk.c.user, 'ignore_auth': False}
    
    is_sysadmin = tk.check_access('sysadmin', context)
    if not is_sysadmin:
        if not tk.c.userobj:
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