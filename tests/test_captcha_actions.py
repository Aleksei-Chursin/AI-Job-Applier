import inspect
from src.controller.custom_controller import CustomController


def test_captcha_actions_registered():
    ctrl = CustomController()
    actions = ctrl.registry.registry.actions
    expected_captcha_actions = [
        "solve_turnstile_or_checkbox",
        "solve_captcha_via_audio",
        "solve_captcha_via_api",
        "pause_for_human_captcha_help",
    ]
    for action_name in expected_captcha_actions:
        assert action_name in actions, f"Action {action_name} not registered in CustomController"
        func = actions[action_name].function
        assert inspect.iscoroutinefunction(func), f"Action {action_name} must be an async function"


if __name__ == "__main__":
    test_captcha_actions_registered()
    print("All CAPTCHA actions verified successfully!")
