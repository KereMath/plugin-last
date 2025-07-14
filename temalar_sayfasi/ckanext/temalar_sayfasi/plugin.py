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
import os # Added for file path operations

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import asbool
from flask import Blueprint

# Yeni eklenen modüller
from ckan.logic import NotAuthorized # Yetkilendirme için
import ckan.model as model # Kullanıcı modeline erişim için
import ckan.lib.uploader as uploader # Dosya yükleme için YENİ EKLENDİ
import ckan.common # Dosya yükleme için YENİ EKLENDİ


# Explicitly import ckan.lib.helpers and assign pager_url to tk.h
# This ensures tk.h.pager_url is available for the Page class.
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
        upload = uploader.get_uploader('theme_background')

        data_dict = {
            'slug':         tk.request.form.get('slug'),
            'name':         tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':        tk.request.form.get('color'),
            'icon':         tk.request.form.get('icon'),
        }

        if 'background_image_upload' in tk.request.files and tk.request.files['background_image_upload'].filename:
            uploaded_file = tk.request.files['background_image_upload']
            try:
                if not hasattr(upload, 'clear'):
                    upload.clear = False
                    log.debug("new_theme: Set 'clear' attribute to False on uploader instance.")
                upload.upload(uploaded_file)
                data_dict['background_image'] = upload.filename
                log.info(f"new_theme: Image uploaded successfully: {upload.filename}")
            except Exception as upload_err:
                log.error(f"new_theme: Error during file upload: {upload_err}", exc_info=True)
                tk.h.flash_error(tk._(f'Görsel yüklenirken bir hata oluştu: {upload_err}'))
                tk.c.errors, tk.c.data = {'background_image_upload': [str(upload_err)]}, data_dict
                return tk.render('theme/new_theme.html')
        else:
            data_dict['background_image'] = None # No file uploaded initially

        try:
            tk.get_action('theme_category_create')(context, data_dict)
            tk.h.flash_success(tk._('Tema başarıyla oluşturuldu.'))
            return tk.h.redirect_to('temalar_sayfasi.dashboard_index')
        except tk.ValidationError as e:
            tk.c.errors, tk.c.data = e.error_dict, data_dict
            if 'background_image' in data_dict and data_dict['background_image']:
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
            if 'background_image' in data_dict and data_dict['background_image']:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), data_dict['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("new_theme: Unexpected error, uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("new_theme: Error cleaning image after unexpected error: %s - %s", full_image_path, err)

    return tk.render('theme/new_theme.html')


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
        # GET isteğinde mevcut verileri yükle
        try:
            tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})['category']
            tk.c.data = tk.c.theme_data # Formu mevcut verilerle doldur
            tk.c.errors = {}
        except tk.ObjectNotFound:
            tk.abort(404, tk._('Tema bulunamadı'))
        except Exception as e:
            log.error(f"Error loading theme data for edit (GET): {e}", exc_info=True)
            tk.abort(500, tk._(f"Sayfa yüklenirken bir hata oluştu: {e}"))
        
        # GET isteği için dataset listesini de çek
        all_ds = tk.get_action('package_search')(context, {
            'rows':          1000,
            'include_private': True
        })
        tk.c.all_datasets = all_ds['results']
        return tk.render('theme/edit_theme.html')


    if tk.request.method == 'POST':
        update_data = {
            'slug':         slug,
            'name':         tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':        tk.request.form.get('color'),
            'icon':         tk.request.form.get('icon'),
        }

        current_theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})['category']
        current_background_image_path = current_theme_data.get('background_image')

        should_delete_old_image = False
        uploaded_new_file = False

        if tk.request.form.get('clear_background_image') == 'true':
            update_data['background_image'] = None
            should_delete_old_image = True
            log.info(f"edit_theme: 'Clear image' checkbox checked for slug: {slug}.")
        elif 'background_image_upload' in tk.request.files and tk.request.files['background_image_upload'].filename:
            uploaded_file = tk.request.files['background_image_upload']
            log.info(f"edit_theme: New image detected for slug: {slug}.")

            upload = uploader.get_uploader('theme_background')
            if not hasattr(upload, 'clear'):
                upload.clear = False
                log.debug("edit_theme: Set 'clear' attribute to False on uploader instance.")

            try:
                # This is where the file gets saved to the storage path
                upload.upload(uploaded_file)
                update_data['background_image'] = upload.filename
                uploaded_new_file = True
                should_delete_old_image = True # If a new file is uploaded, the old one should be removed.
                log.info(f"edit_theme: Image uploaded successfully for theme {slug}: {upload.filename}")
            except Exception as upload_err:
                log.error(f"edit_theme: Error during file upload for theme {slug}: {upload_err}", exc_info=True)
                tk.h.flash_error(tk._(f'Görsel yüklenirken bir hata oluştu: {upload_err}'))
                tk.c.errors, tk.c.data = {'background_image_upload': [str(upload_err)]}, tk.request.form
                # Ensure existing image path is retained if upload failed
                update_data['background_image'] = current_background_image_path
                return tk.render('theme/edit_theme.html')
        else:
            # No new file uploaded, and 'clear' not checked. Retain existing path.
            update_data['background_image'] = current_background_image_path
            log.info(f"edit_theme: No image changes for slug: {slug}, retaining existing path: {current_background_image_path}.")


        # Perform deletion of the old image if flagged and a path exists
        if should_delete_old_image and current_background_image_path:
            full_old_image_path = os.path.join(tk.config.get('ckan.storage_path'), current_background_image_path)
            try:
                if os.path.exists(full_old_image_path):
                    os.remove(full_old_image_path)
                    log.info(f"edit_theme: Old background image deleted: {full_old_image_path}")
                else:
                    log.info(f"edit_theme: Old background image not found to delete: {full_old_image_path}")
            except OSError as e:
                log.warning(f"edit_theme: Error deleting old background image: {full_old_image_path} - {e}", exc_info=True)


        try:
            # Call the action to update theme data in the database
            tk.get_action('theme_category_update')(context, update_data)
            log.info(f"edit_theme: Called theme_category_update for {slug} with data: {update_data.get('background_image')}")

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
            log.error(f"edit_theme: Validation error during theme update for {slug}: {e.error_dict}", exc_info=True)
            tk.c.errors, tk.c.data = e.error_dict, tk.request.form
            tk.h.flash_error(str(e))
            if uploaded_new_file and 'background_image' in update_data and update_data['background_image']:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), update_data['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("edit_theme: Validation error, uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("edit_theme: Error cleaning image after validation error: %s - %s", full_image_path, err)
        except Exception as e:
            log.error(f"edit_theme: Unexpected error during theme update for {slug}: {e}", exc_info=True)
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form
            if uploaded_new_file and 'background_image' in update_data and update_data['background_image']:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), update_data['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("edit_theme: Unexpected error, uploaded image cleaned: %s", full_image_path)
                except OSError as err:
                    log.warning("edit_theme: Error cleaning image after unexpected error: %s - %s", full_image_path, err)

    # If POST fails (due to validation or other exception before redirect), re-render the form
    # and ensure data is populated for user correction.
    try:
        # Re-fetch theme_data to ensure latest state is shown if there were errors
        tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})['category']
        all_ds = tk.get_action('package_search')(context, {
            'rows':          1000,
            'include_private': True
        })
        tk.c.all_datasets = all_ds['results']
        return tk.render('theme/edit_theme.html')
    except tk.ObjectNotFound:
        tk.abort(404, tk._('Tema bulunamadı'))
    except Exception as e:
        log.error(f"edit_theme: Error re-rendering edit page after POST failure: {e}", exc_info=True)
        tk.abort(500, tk._(f"Sayfa yüklenirken beklenmeyen bir hata oluştu: {e}"))


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

        update_data = {
            'slug':         slug,
            'name':         tk.request.form.get('name'),
            'description': tk.request.form.get('description'),
            'color':        tk.request.form.get('color'),
            'icon':         tk.request.form.get('icon'),
        }

        # Mevcut tema bilgisini al (görsel yolunu bilmek için)
        current_theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})['category']
        current_background_image_path = current_theme_data.get('background_image')

        should_delete_old_image = False
        uploaded_new_file = False # Flag to track if a new file was actually uploaded

        # Görseli kaldırıp kaldırmadığımızı kontrol et
        if tk.request.form.get('clear_background_image') == 'true':
            update_data['background_image'] = None # Veritabanında boş olarak kaydet
            should_delete_old_image = True
            log.info("Clear image checkbox checked for slug: %s", slug)
        # Yeni bir görsel yüklenip yüklenmediğini kontrol et
        elif 'background_image_upload' in tk.request.files and tk.request.files['background_image_upload'].filename:
            uploaded_file = tk.request.files['background_image_upload']
            log.info("New image uploaded for slug: %s", slug)

            # --- Critical Change: Explicitly set upload.clear = False if it doesn't exist ---
            upload = uploader.get_uploader('theme_background')
            # Check if 'clear' attribute exists on the uploader instance
            if not hasattr(upload, 'clear'):
                upload.clear = False # Set it to False to prevent the AttributeError
                log.debug("Set 'clear' attribute to False on uploader instance.")

            try:
                # The 'upload' method might still handle some internal clearing,
                # but by setting 'clear' to False, we avoid the AttributeError.
                upload.upload(uploaded_file)
                update_data['background_image'] = upload.filename
                uploaded_new_file = True # Set flag
                should_delete_old_image = True # A new file implies old one should be deleted
            except Exception as upload_err:
                log.error(f"Error during file upload for theme {slug}: {upload_err}", exc_info=True)
                tk.h.flash_error(tk._(f'Görsel yüklenirken bir hata oluştu: {upload_err}'))
                # Re-render form with current data and errors
                tk.c.errors, tk.c.data = {'background_image_upload': [str(upload_err)]}, tk.request.form
                # Ensure existing image path is retained if upload failed, so it doesn't disappear from form
                update_data['background_image'] = current_background_image_path
                return tk.render('theme/edit_theme.html')
        else:
            # Ne yeni bir dosya yüklendi ne de mevcut dosya silindi, o zaman mevcut yolu koru
            update_data['background_image'] = current_background_image_path
            log.info("No image changes for slug: %s, retaining existing path.", slug)


        # Perform deletion of the old image if flagged and a path exists
        # This block now handles deletion for both 'clear' action and 'new upload' action.
        if should_delete_old_image and current_background_image_path:
            full_old_image_path = os.path.join(tk.config.get('ckan.storage_path'), current_background_image_path)
            try:
                if os.path.exists(full_old_image_path): # Check if file exists before trying to delete
                    os.remove(full_old_image_path)
                    log.info("Eski arka plan görseli silindi: %s", full_old_image_path)
                else:
                    log.info("Silinecek eski arka plan görseli bulunamadı veya zaten silinmiş: %s", full_old_image_path)
            except OSError as e:
                log.warning("Eski arka plan görseli silinirken hata oluştu: %s - %s", full_old_image_path, e)


        try:
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
            # Hata durumunda, eğer yeni dosya yüklendiyse onu temizle
            if uploaded_new_file and 'background_image' in update_data and update_data['background_image']:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), update_data['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("Tema güncellenirken hata oluştu, yüklenen görsel temizlendi: %s", full_image_path)
                except OSError as err:
                    log.warning("Hata durumunda yüklenen görsel silinirken hata oluştu: %s - %s", full_image_path, err)
        except Exception as e:
            log.error(f"Tema güncellenirken hata: {e}", exc_info=True)
            tk.h.flash_error(tk._(f'Bir hata oluştu: {e}'))
            tk.c.data = tk.request.form
            # Hata durumunda, eğer yeni dosya yüklendiyse onu temizle
            if uploaded_new_file and 'background_image' in update_data and update_data['background_image']:
                full_image_path = os.path.join(tk.config.get('ckan.storage_path'), update_data['background_image'])
                try:
                    if os.path.exists(full_image_path):
                        os.remove(full_image_path)
                        log.info("Tema güncellenirken hata oluştu, yüklenen görsel temizlendi: %s", full_image_path)
                except OSError as err:
                    log.warning("Hata durumunda yüklenen görsel silinirken hata oluştu: %s - %s", full_image_path, err)


    try:
        tk.c.theme_data = tk.get_action('theme_category_show')({}, {'slug': slug})
        all_ds = tk.get_action('package_search')(context, {
            'rows':          1000,
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
        # Tema silinmeden önce ilişkili görseli de silelim
        current_theme_data = tk.get_action('theme_category_show')(context, {'slug': slug})['category']
        background_image_path = current_theme_data.get('background_image')
        
        tk.get_action('theme_category_delete')(context, {'slug': slug})
        
        # Eğer bir arka plan görseli varsa, onu da temizle
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