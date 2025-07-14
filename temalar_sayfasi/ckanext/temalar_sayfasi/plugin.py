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
import os

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import asbool
from flask import Blueprint

from ckan.logic import NotAuthorized
import ckan.model as model
import ckan.lib.uploader as uploader
import ckan.common


import ckan.lib.helpers as _helpers
tk.h.pager_url = _helpers.pager_url


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
        # Prepare data_dict from form
        data_dict = {
            'slug':         tk.request.form.get('slug'),
            'name':         tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':        tk.request.form.get('color'),
            'icon':         tk.request.form.get('icon'),
            'opacity':      float(tk.request.form.get('opacity', 1.0)), # YENİ EKLENDİ: opacity'yi al
            # Pass original filename for the uploader (it will modify this)
            'background_image': tk.request.form.get('background_image'), # This might be old path on GET
            'clear_background_image': tk.request.form.get('clear_background_image')
        }

        # IMPORTANT: Directly pass the uploaded file object to data_dict
        # The uploader expects to find the file here to process it.
        # It's usually under a key matching the form field name.
        if 'background_image_upload' in tk.request.files and tk.request.files['background_image_upload'].filename:
            data_dict['background_image_upload'] = tk.request.files['background_image_upload']
            log.info(f"new_theme: Detected new file upload: {data_dict['background_image_upload'].filename}")
        else:
            data_dict['background_image_upload'] = None
            log.info("new_theme: No new file uploaded.")


        try:
            # Get the uploader instance (associated with 'theme_background' prefix)
            # Pass original filename to the uploader's init if it's an old file being replaced/cleared
            # This 'old_filename' is used by uploader.py's internal logic for deletion.
            # `data_dict.get('background_image')` will be empty string if there was no prior image,
            # or the old image path if it exists.
            upload = uploader.get_uploader('theme_background', data_dict.get('background_image'))

            # --- CRITICAL FIX START: Call update_data_dict before upload() ---
            # This method processes the uploaded file, sets upload.filename/filepath,
            # and updates data_dict['background_image'] with the new (or cleared) filename.
            upload.update_data_dict(data_dict,
                                    url_field='background_image',
                                    file_field='background_image_upload',
                                    clear_field='clear_background_image')
            log.info(f"new_theme: After update_data_dict, data_dict['background_image'] is: {data_dict.get('background_image')}")
            # --- CRITICAL FIX END ---

            # Now, if an actual file was provided (and processed by update_data_dict), call upload().
            # upload.filename will now be correctly set by update_data_dict.
            if upload.filename:
                # The 'upload' method of ckan.lib.uploader.Upload class
                # uses self.filepath which was set by update_data_dict.
                upload.upload() # No need to pass uploaded_file or max_size here if update_data_dict handled it.
                log.info(f"new_theme: File physically uploaded to storage path. Final filename: {upload.filename}")
            else:
                log.info("new_theme: No file to physically upload (either no new file or cleared).")


            # Old image deletion logic (now simplified, as uploader.update_data_dict/upload() handles it mostly)
            # If clear_background_image was true and there was an old file, update_data_dict will have set
            # data_dict['background_image'] to None, and uploader.upload() (if it runs) handles deleting old_filepath.
            # We explicitly check this in `edit_theme` where there is more complexity.
            # For new_theme, it's simpler: if an image was successfully assigned (data_dict['background_image'] is not None
            # and a file was uploaded), it's considered new.

            # Proceed with theme creation (data_dict now contains the correct background_image path or None)
            tk.get_action('theme_category_create')(context, data_dict)
            tk.h.flash_success(tk._('Tema başarıyla oluşturuldu.'))
            return tk.h.redirect_to('temalar_sayfasi.dashboard_index')
        except tk.ValidationError as e:
            tk.c.errors, tk.c.data = e.error_dict, data_dict
            # If validation fails, and a file was uploaded and might be in storage, clean it.
            # We use `data_dict.get('background_image')` as this is what the uploader would have set.
            if data_dict.get('background_image'):
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), data_dict['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("new_theme: Validation error, uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("new_theme: Error cleaning image after validation error: %s - %s", full_image_path, err)
            tk.h.flash_error(tk._('Lütfen formdaki hataları düzeltin.'))
        except Exception as e:
            log.error(f"new_theme: Unexpected error during theme creation: {e}", exc_info=True)
            tk.h.flash_error(tk._(f'Tema oluşturulurken beklenmeyen bir hata oluştu: {e}'))
            tk.c.data = data_dict
            if data_dict.get('background_image'):
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), data_dict['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("new_theme: Unexpected error, uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("new_theme: Error cleaning image after unexpected error: %s - %s", full_image_path, err)

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

        is_sysadmin = tk.c.userobj and tk.c.userobj.sysadmin
        tk.c.is_sysadmin = is_sysadmin

        tk.c.user_theme_role_for_this_theme = None
        if not is_sysadmin and tk.c.userobj:
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
            def __init__(self, items, item_count, current_slug):
                self.items          = items
                self.item_count     = item_count
                self.q              = tk.request.args.get('q', '')
                self.sort_by_selected = tk.request.args.get('sort', '')
                self.current_slug = current_slug

                def _generate_pager_html(endpoint_name, item_count, items_per_page, current_page, slug_param, q=''):
                    total_pages = (item_count + items_per_page - 1) // items_per_page
                    if total_pages <= 1:
                        return ''

                    html_parts = []

                    if current_page > 1:
                        prev_url = tk.h.pager_url(endpoint_name, current_page - 1, slug=slug_param, q=q)
                        html_parts.append(f'<li class="previous"><a href="{prev_url}">« Previous</a></li>')

                    for i in range(1, total_pages + 1):
                        page_url = tk.h.pager_url(endpoint_name, i, slug=slug_param, q=q)
                        active_class = 'active' if i == current_page else ''
                        html_parts.append(f'<li class="{active_class}"><a href="{page_url}">{i}</a></li>')

                    if current_page < total_pages:
                        next_url = tk.h.pager_url(endpoint_name, current_page + 1, slug=slug_param, q=q)
                        html_parts.append(f'<li class="next"><a href="{next_url}">Next »</a></li>')

                    return '<div class="pagination"><ul>' + ''.join(html_parts) + '</ul></div>'


                def _pager_callable(**kwargs):
                    q_param = kwargs.get('q', '')

                    current_page_from_request = int(tk.request.args.get('page', 1))

                    return _generate_pager_html(
                        endpoint_name='temalar_sayfasi.read',
                        item_count=self.item_count,
                        items_per_page=ITEMS_PER_PAGE,
                        current_page=current_page_from_request,
                        slug_param=self.current_slug,
                        q=q_param
                    )

                self.pager = _pager_callable if self.item_count > ITEMS_PER_PAGE else (lambda **kw: '')


        tk.c.page = Page(packages, total, slug)

        tracking_enabled = asbool(tk.config.get('ckan.tracking_enabled', False))
        tk.c.sort_by_options = [
            (tk._('Relevance'),    'score desc, metadata_modified desc'),
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
        log.warning(f"User {tk.c.user or 'anonymous'} not authorized to edit theme {slug}.")
        raise NotAuthorized(_('Bu temayı düzenlemek için yetkiniz yok.'))


    if tk.request.method == 'GET':
        try:
            theme_full_data = tk.get_action('theme_category_show')({}, {'slug': slug})
            tk.c.theme_data = theme_full_data
            tk.c.data = theme_full_data['category']
            tk.c.errors = {}
            log.info(f"edit_theme (GET): Loaded theme data for {slug}. Category name: {tk.c.theme_data['category']['name']}")
        except tk.ObjectNotFound:
            tk.abort(404, tk._('Tema bulunamadı'))
        except Exception as e:
            log.error(f"Error loading theme data for edit (GET): {e}", exc_info=True)
            tk.abort(500, tk._(f"Sayfa yüklenirken bir hata oluştu: {e}"))

        all_ds = tk.get_action('package_search')(context, {
            'rows':            1000,
            'include_private': True
        })
        tk.c.all_datasets = all_ds['results']
        return tk.render('theme/edit_theme.html')


    if tk.request.method == 'POST':
        # Prepare data_dict from form fields
        # Note: 'background_image' will initially hold the OLD path if present,
        # or an empty string/None if no old image.
        data_dict = {
            'slug':         slug,
            'name':         tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':        tk.request.form.get('color'),
            'icon':         tk.request.form.get('icon'),
            'opacity':      float(tk.request.form.get('opacity', 1.0)), # YENİ EKLENDİ: opacity'yi al
            'background_image': tk.request.form.get('background_image'), # This is the existing image path from form if any
            'clear_background_image': tk.request.form.get('clear_background_image') # True/False based on checkbox
        }

        # IMPORTANT: Pass the actual uploaded file object into data_dict under the correct key
        if 'background_image_upload' in tk.request.files and tk.request.files['background_image_upload'].filename:
            data_dict['background_image_upload'] = tk.request.files['background_image_upload']
            log.info(f"edit_theme (POST): New file detected in request files: {data_dict['background_image_upload'].filename}")
        else:
            data_dict['background_image_upload'] = None
            log.info("edit_theme (POST): No new file provided in request.")


        # Retrieve current_theme_data for existing image path *before* potential modification by uploader
        # This is needed for deletion logic later.
        current_theme_full_data = tk.get_action('theme_category_show')(context, {'slug': slug})
        current_background_image_path = current_theme_full_data['category'].get('background_image')


        try:
            # Get the uploader instance. Pass the object_type and the old filename.
            # The old_filename is crucial for uploader's internal clear logic.
            upload = uploader.get_uploader('theme_background', old_filename=current_background_image_path)
            log.debug(f"edit_theme (POST): Uploader initialized with old_filename: {current_background_image_path}")

            # --- CRITICAL FIX: Call update_data_dict before upload() ---
            # This method processes the uploaded file (if any), sets upload.filename/filepath on the uploader object,
            # and updates data_dict['background_image'] with the new (or cleared) filename.
            upload.update_data_dict(data_dict,
                                    url_field='background_image',       # This is where the new filename will go in data_dict
                                    file_field='background_image_upload', # This is where the uploaded file object is in data_dict
                                    clear_field='clear_background_image') # This is the clear checkbox value

            log.info(f"edit_theme (POST): After update_data_dict: upload.filename='{upload.filename}', upload.filepath='{upload.filepath}', data_dict['background_image']='{data_dict.get('background_image')}'")

            # Now, if an actual file was provided and processed by update_data_dict, call upload().
            # upload.filename will be correctly set by update_data_dict if a file was provided.
            if upload.filename: # Only call upload() if there's a new filename to write
                upload.upload() # This method uses self.filepath (set by update_data_dict) to save the file
                log.info(f"edit_theme (POST): File physically uploaded to storage path. Final filename: {upload.filename}")
            else:
                log.info("edit_theme (POST): No new file to physically upload (either no new file or it was cleared).")

            # data_dict['background_image'] now holds the *correct* path that should be saved to DB
            # (either new path, None if cleared, or old path if no changes)

            # Old image deletion logic: The uploader.upload() method itself handles deleting old_filepath
            # if `self.clear` is True (which update_data_dict sets if the clear checkbox is true,
            # or if a new file overwrites an old one). We don't need a separate os.remove here.
            # Removed redundant `should_delete_old_image` logic here.

            # Proceed with theme creation (data_dict now contains the correct background_image path or None)
            tk.get_action('theme_category_update')(context, data_dict)
            log.info(f"edit_theme (POST): Called theme_category_update for {slug} with background_image: {data_dict.get('background_image')}")


            # Handle dataset assignments (unchanged logic)
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
            log.error(f"edit_theme (POST): Validation error during theme update for {slug}: {e.error_dict}", exc_info=True)
            tk.c.errors, tk.c.data = e.error_dict, tk.request.form
            tk.h.flash_error(str(e))
            # If validation fails, and a file was successfully uploaded (and not cleaned by uploader.py itself due to its logic)
            # we need to make sure it's not left behind if the transaction rolls back or form is re-rendered.
            # `data_dict.get('background_image')` will contain the new file path if it was set successfully by uploader.update_data_dict.
            if data_dict.get('background_image') and data_dict.get('background_image') != current_background_image_path:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), data_dict['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("edit_theme (POST): Validation error, newly uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("edit_theme (POST): Error cleaning newly uploaded image after validation error: %s - %s", full_image_path, err)
            tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
            all_ds = tk.get_action('package_search')(context, {'rows': 1000, 'include_private': True})
            tk.c.all_datasets = all_ds['results']
            return tk.render('theme/edit_theme.html')
        except Exception as e: # Catch any other unexpected errors
            log.error(f"edit_theme (POST): Unexpected error during theme update for {slug}: {e}", exc_info=True)
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form
            # Similar cleanup for unexpected errors
            if data_dict.get('background_image') and data_dict.get('background_image') != current_background_image_path:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), data_dict['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("edit_theme (POST): Unexpected error, newly uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("edit_theme (POST): Error cleaning newly uploaded image after unexpected error: %s - %s", full_image_path, err)
            tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
            all_ds = tk.get_action('package_search')(context, {'rows': 1000, 'include_private': True})
            tk.c.all_datasets = all_ds['results']
            return tk.render('theme/edit_theme.html')


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
            raise NotAuthorized('Bu temayı silmek for yetkiniz yok.')


    try:
        current_theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})['category']
        background_image_path = current_theme_data.get('background_image')

        tk.get_action('theme_category_delete')(context, {'slug': slug})

        if background_image_path:
            full_image_path = os.path.join(tk.config.get('ckan.storage_path'), background_image_path)
            try:
                if os.path.exists(full_image_path):
                    os.remove(full_image_path)
                    log.info("Tema silindi, ilişkili arka plan görseli de silindi: %s", full_image_path)
                else:
                    log.info("Tema silindi ancak ilişkili arka plan görseli bulunamadı: %s", full_image_path)
            except OSError as e:
                log.warning("Tema silinirken arka plan görseli silinirken hata oluştu: %s - %s", full_image_path, e)

        tk.h.flash_success(tk._('Tema başarıyla silindi.'))
        return tk.h.redirect_to('temalar_sayfasi.index')
    except tk.ValidationError as e:
        tk.h.flash_error(str(e))
        return tk.h.redirect_to('temalar_sayfasi.edit', slug=slug)
    except Exception as e:
        log.error(f"Tema silinirken hata: {e}", exc_info=True)
        tk.h.flash_error(tk._(f'Tema silinirken bir hata oluştu: {e}'))
        return tk.h.redirect_to('temalar_sayfasi.edit', slug=slug)


# ----------------------------------------------------------------------
# CKAN Plugin tanımı
# ----------------------------------------------------------------------

class TemalarSayfasiPlugin(p.SingletonPlugin):
    p.implements(p.IBlueprint)
    p.implements(p.IConfigurer)

    def update_config(self, config_):
        tk.add_template_directory(config_, 'templates')

    def get_blueprint(self):
        bp = Blueprint('temalar_sayfasi', __name__)

        bp.add_url_rule('/temalar', endpoint='index', view_func=index)

        bp.add_url_rule('/temalar/yeni', endpoint='new', view_func=new_theme, methods=['GET', 'POST'])

        bp.add_url_rule('/temalar/<slug>', endpoint='read', view_func=read_theme)

        bp.add_url_rule('/temalar/<slug>/edit', endpoint='edit', view_func=edit_theme, methods=['GET', 'POST'])

        bp.add_url_rule('/temalar/<slug>/delete', endpoint='delete', view_func=delete_theme, methods=['POST'])

        bp.add_url_rule('/dashboard/temalar', endpoint='dashboard_index', view_func=dashboard_themes)

        return bp