import logging
import datetime
import json

from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http.response import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

# from data.files import get_text, get_submission_text
from provider import aplus
from data.models import Course, Comparison
from radar.config import provider_config, configured_function
from review.decorators import access_resource
from review.forms import ExerciseForm, ExerciseTokenizerForm


logger = logging.getLogger("radar.review")


@login_required
def index(request):
    return render(request, "review/index.html", {
        "hierarchy": (("Radar", None),),
        "courses": Course.objects.get_available_courses(request.user)
    })


@access_resource
def course(request, course_key=None, course=None):
    return render(request, "review/course.html", {
        "hierarchy": (("Radar", reverse("index")), (course.name, None)),
        "course": course,
        "exercises": course.exercises.all()
    })


@access_resource
def course_histograms(request, course_key=None, course=None):
    return render(request, "review/course_histograms.html", {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      ("Histograms", None)),
        "course": course,
        "exercises": course.exercises.all()
    })


@access_resource
def exercise(request, course_key=None, exercise_key=None, course=None, exercise=None):
    return render(request, "review/exercise.html", {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      (exercise.name, None)),
        "course": course,
        "exercise": exercise,
        "comparisons": exercise.top_comparisons(),
    })


@access_resource
def comparison(request, course_key=None, exercise_key=None, ak=None, bk=None, ck=None, course=None, exercise=None):
    comparison = get_object_or_404(Comparison, submission_a__exercise=exercise, pk=ck,
                                   submission_a__student__key=ak, submission_b__student__key=bk)
    if request.method == "POST":
        result = "review" in request.POST and comparison.update_review(request.POST["review"])
        if request.is_ajax():
            return JsonResponse({ "success": result })

    reverse_flag = False
    a = comparison.submission_a
    b = comparison.submission_b
    if "reverse" in request.GET:
        reverse_flag = True
        a = comparison.submission_b
        b = comparison.submission_a

    p_config = provider_config(course.provider)
    get_submission_text = configured_function(p_config, "get_submission_text")
    return render(request, "review/comparison.html", {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      (exercise.name, reverse("exercise",
                                              kwargs={ "course_key": course.key, "exercise_key": exercise.key })),
                      ("%s vs %s" % (a.student.key, b.student.key), None)),
        "course": course,
        "exercise": exercise,
        "comparisons": exercise.comparisons_for_student(a.student),
        "comparison": comparison,
        "reverse": reverse_flag,
        "a": a,
        "b": b,
        "source_a": get_submission_text(a, p_config),
        "source_b": get_submission_text(b, p_config)
    })


@access_resource
def marked_submissions(request, course_key=None, course=None):
    comparisons = Comparison.objects\
        .filter(submission_a__exercise__course=course, review__gte=5)\
        .order_by("submission_a__created")\
        .select_related("submission_a", "submission_b","submission_a__exercise", "submission_a__student", "submission_b__student")
    suspects = {}
    for c in comparisons:
        for s in (c.submission_a.student, c.submission_b.student):
            if s.id not in suspects:
                suspects[s.id] = { 'key':s.key, 'sum':0, 'comparisons':[] }
            suspects[s.id]['sum'] += c.review
            suspects[s.id]['comparisons'].append(c)
    return render(request, "review/marked.html", {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      ("Marked submissions", None)),
        "course": course,
        "suspects": sorted(suspects.values(), reverse=True, key=lambda e: e['sum']),
    })


def leafs_with_radar_config(exercises):
    """
    Return an iterator yielding dictionaries of leaf exercises that have Radar configurations.
    """
    if not exercises:
        return
    for exercise in exercises:
        child_exercises = exercise.get("exercises")
        if child_exercises:
            yield from leafs_with_radar_config(child_exercises)
        else:
            radar_config = aplus.get_radar_config(exercise)
            if radar_config:
                yield radar_config


@access_resource
def configure_course(request, course_key=None, course=None):
    context = {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      ("Configure", None)),
        "course": course,
        "errors": []
    }
    if request.method != "POST":
        client = request.user.get_api_client(course.namespace)
        response = client.load_data(course.url)
        context["fetched_at"] = datetime.datetime.now().isoformat()
        exercises = response.get("exercises", [])
        if not exercises:
            context["errors"].append("No courses found for course %s", repr(course))
        else:
            exercises = list(leafs_with_radar_config(exercises))
            for exercise in exercises:
                exercise["new"] = not course.has_exercise(exercise["exercise_key"])
            context["exercises"] = {
                "iter": exercises,
                "json": json.dumps(exercises)
            }
    elif "override_configurations" in request.POST:
        exercises = json.loads(request.POST["exercises_json"])
        for exercise_data in exercises:
            key_str = str(exercise_data["exercise_key"])
            if course.has_exercise(key_str):
                exercise = course.get_exercise(key_str)
                exercise.set_from_config(exercise_data)
                exercise.save()
                Comparison.objects.clean_for_exercise(exercise)
                exercise.clear_tokens_and_matches()
            else:
                logger.error("Exercise '%s' unexpectedly does not exist, cannot configure exercise.", key_str)
        context["exercises"] = { "iter": exercises }
        context["override_success"] = True
    return render(request, "review/configure.html", context)


@access_resource
def exercise_settings(request, course_key=None, exercise_key=None, course=None, exercise=None):
    p_config = provider_config(course.provider)
    if request.method == "POST":
        form = ExerciseForm(request.POST)
        form_tokenizer = ExerciseTokenizerForm(request.POST)
        if "save" in request.POST:
            if form.is_valid():
                form.save(exercise)
                return redirect("course", course_key=course.key)
        if "save_and_clear" in request.POST:
            if form_tokenizer.is_valid():
                form_tokenizer.save(exercise)
                return redirect("course", course_key=course.key)
        if "provider_reload" in request.POST:
            configured_function(p_config, "reload")(exercise, p_config)
            return redirect("course", course_key=course.key)
    else:
        form = ExerciseForm({
            "name": exercise.name,
            "paused": exercise.paused
        })
        form_tokenizer = ExerciseTokenizerForm({
            "tokenizer": exercise.tokenizer,
            "minimum_match_tokens": exercise.minimum_match_tokens,
            "template": aplus.load_exercise_template(exercise, p_config),
        })
    return render(request, "review/exercise_settings.html", {
        "hierarchy": (("Radar", reverse("index")),
                      (course.name, reverse("course", kwargs={ "course_key": course.key })),
                      ("%s settings" % (exercise.name), None)),
        "course": course,
        "exercise": exercise,
        "form": form,
        "form_tokenizer": form_tokenizer,
        "provider_reload": "reload" in p_config
    })
