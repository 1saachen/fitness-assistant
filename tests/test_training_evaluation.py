import json


def test_offline_evaluation_never_constructs_network_provider(tmp_path, monkeypatch):
    from fitness import training_evaluation as evaluation
    def forbidden(*args, **kwargs):
        raise AssertionError('offline evaluation attempted network setup')
    monkeypatch.setattr(evaluation, 'OpenAICompatibleProvider', forbidden)
    report = evaluation.evaluate()
    assert report['mode'] == 'scripted'
    assert report['model_quality'] == 'not_evaluated'
    assert len(report['cases']) == 8
    assert all(row['engineering_pass'] for row in report['cases'])
    assert all(row['human_review']['status'] == 'pending' for row in report['cases'])
    assert evaluation.main(['--output-dir', str(tmp_path)]) == 0
    saved = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert saved['model_quality'] == 'not_evaluated'
    assert '未执行真实模型质量评估' in (tmp_path / 'report.md').read_text(encoding='utf-8')


def test_failed_live_evaluation_reports_errors_without_reading_local_profile(monkeypatch):
    from fitness import training_evaluation as evaluation
    from fitness.config import Settings
    from fitness.provider import ProviderError
    class BrokenProvider:
        def complete(self, *args, **kwargs):
            raise ProviderError('timeout')
    monkeypatch.setattr(evaluation, 'OpenAICompatibleProvider', lambda settings: BrokenProvider())
    report = evaluation.evaluate(live=True, settings=Settings(live_enabled=True))
    assert report['mode'] == 'live'
    assert any(row['reason'] == 'timeout' for row in report['cases'])
    assert not all(row['engineering_pass'] for row in report['cases'])
    assert report['model_quality'] == 'requires_independent_review'
