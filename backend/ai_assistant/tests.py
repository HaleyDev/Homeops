from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from system_setting.services import EffectiveModelConfig, ModelConfigurationError

from .services import chat_stream, get_runner, get_session_service


class SessionServiceTests(SimpleTestCase):
    @patch("google.adk.sessions.DatabaseSessionService")
    def test_uses_postgresql_asyncpg_url(self, service_class):
        database = {
            "NAME": "homeops",
            "USER": "homeops",
            "PASSWORD": "secret",
            "HOST": "db",
            "PORT": "5432",
        }
        with (
            patch("ai_assistant.services._session_service", None),
            patch("django.conf.settings.DATABASES", {"default": database}),
        ):
            result = get_session_service()

        self.assertIs(result, service_class.return_value)
        args, kwargs = service_class.call_args
        self.assertEqual(
            args[0],
            "postgresql+asyncpg://homeops:secret@db:5432/homeops",
        )
        self.assertEqual(kwargs["poolclass"].__name__, "NullPool")


class PerTurnRunnerTests(SimpleTestCase):
    def setUp(self):
        self.first_config = EffectiveModelConfig(
            model_id=1,
            provider_id=1,
            model_key="model-a",
            model_type="text",
            protocol="openai_compatible",
            base_url="https://a.example.com/v1",
            dimensions=None,
            api_key="secret-a",
            parameters={"temperature": 0.1},
        )
        self.second_config = EffectiveModelConfig(
            model_id=2,
            provider_id=2,
            model_key="model-b",
            model_type="text",
            protocol="openai_compatible",
            base_url="https://b.example.com/v1",
            dimensions=None,
            api_key="secret-b",
            parameters={"temperature": 0.9},
        )

    @patch("google.adk.runners.Runner")
    @patch("ai_assistant.services.create_agent")
    @patch("ai_assistant.services.get_session_service")
    @patch("ai_assistant.services.get_effective_model_config")
    def test_every_turn_reloads_config_and_creates_new_runner(
        self,
        get_config,
        get_session_service,
        create_agent,
        runner_class,
    ):
        get_config.side_effect = [self.first_config, self.second_config]
        session_service = Mock()
        get_session_service.return_value = session_service
        first_agent, second_agent = Mock(), Mock()
        create_agent.side_effect = [first_agent, second_agent]
        first_runner, second_runner = Mock(), Mock()
        runner_class.side_effect = [first_runner, second_runner]

        first_result = get_runner()
        second_result = get_runner()

        self.assertEqual(get_config.call_count, 2)
        self.assertEqual(
            create_agent.call_args_list,
            [call(self.first_config), call(self.second_config)],
        )
        self.assertIs(first_result[0], first_runner)
        self.assertIs(second_result[0], second_runner)
        self.assertIs(first_result[1], session_service)
        self.assertIs(second_result[1], session_service)
        runner_class.assert_has_calls(
            [
                call(
                    agent=first_agent,
                    app_name="homeops_assistant",
                    session_service=session_service,
                ),
                call(
                    agent=second_agent,
                    app_name="homeops_assistant",
                    session_service=session_service,
                ),
            ]
        )

    @patch("ai_assistant.services.get_runner")
    def test_missing_config_returns_safe_sse_error(self, get_turn_runner):
        get_turn_runner.side_effect = ModelConfigurationError(
            "Text model is not configured. Contact an administrator."
        )

        frames = list(
            chat_stream(
                "user-id",
                "session-id",
                "hello",
                on_complete=Mock(),
            )
        )

        self.assertIn("event: session", frames[0])
        self.assertIn("event: error", frames[1])
        self.assertIn("Text model is not configured. Contact an administrator.", frames[1])
        self.assertEqual(len(frames), 2)

    @patch("ai_assistant.agent.agent.Agent")
    @patch("ai_assistant.agent.agent.LiteLlm")
    def test_agent_uses_configuration_snapshot(self, lite_llm, agent_class):
        from .agent.agent import create_agent

        create_agent(self.first_config)

        lite_llm.assert_called_once_with(
            model="openai/model-a",
            api_key="secret-a",
            base_url="https://a.example.com/v1",
            temperature=0.1,
        )
        self.assertEqual(agent_class.call_args.kwargs["model"], lite_llm.return_value)
