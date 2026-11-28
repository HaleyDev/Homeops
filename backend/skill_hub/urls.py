from django.urls import path

from . import views

urlpatterns = [
    path('skills/', views.SkillListView.as_view(), name='skill-list'),
    path('skills/validate/', views.SkillValidateView.as_view(), name='skill-validate'),
    path('skills/tags/', views.SkillTagsView.as_view(), name='skill-tags'),
    path('skills/<slug:name>/', views.SkillDetailView.as_view(), name='skill-detail'),
    path(
        'skills/<slug:name>/versions/',
        views.SkillVersionListView.as_view(),
        name='skill-version-list',
    ),
    path(
        'skills/<slug:name>/versions/<str:version>/',
        views.SkillVersionDetailView.as_view(),
        name='skill-version-detail',
    ),
    path(
        'skills/<slug:name>/versions/<str:version>/publish/',
        views.SkillVersionPublishView.as_view(),
        name='skill-version-publish',
    ),
    path(
        'skills/<slug:name>/download/',
        views.SkillDownloadView.as_view(),
        name='skill-download',
    ),
    path(
        'skills/<slug:name>/versions/<str:version>/download/',
        views.SkillDownloadView.as_view(),
        name='skill-version-download',
    ),
]
