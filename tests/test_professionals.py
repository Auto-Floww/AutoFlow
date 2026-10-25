"""Professional management and tenant isolation."""
from app.extensions import db
from app.models import Professional, Service
from tests.test_appointments import _schedule, _future_monday

BASE = '/appointments/professionals'


def test_professional_lifecycle(client, login_as, tenant_user):
    login_as(tenant_user)
    service = Service(company_id=tenant_user.company_id, name='Consulta')
    db.session.add(service)
    db.session.commit()
    response = client.post(BASE, json={'name': 'Ana', 'email': 'ANA@example.com', 'service_ids': [service.id]})
    assert response.status_code == 201
    person_id = response.json['data']['id']
    assert response.json['data']['service_ids'] == [service.id]
    assert 'Ana' in client.get(BASE + '?q=ana@example.com').text
    assert 'ana@example.com' not in client.get(BASE + '?q=missing').text
    response = client.post(f'{BASE}/{person_id}', data={'name': 'Beatriz', 'services_present': '', 'is_active': 'false'}, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 200
    assert response.json['data']['service_ids'] == []
    assert response.json['data']['is_active'] is False
    assert 'Beatriz' not in client.get('/appointments').text
    assert client.post(f'{BASE}/{person_id}/delete', json={}).status_code == 200
    assert db.session.get(Professional, person_id) is None


def test_professional_tenant_isolation(client, login_as, tenant_user, company_factory):
    other = company_factory()
    person = Professional(company_id=other.id, name='Outra empresa')
    service = Service(company_id=other.id, name='Privado')
    db.session.add_all([person, service])
    db.session.commit()
    login_as(tenant_user)
    assert 'Outra empresa' not in client.get(BASE).text
    assert client.post(f'{BASE}/{person.id}', json={'name': 'Alterado'}).status_code == 404
    assert client.post(f'{BASE}/{person.id}/delete', json={}).status_code == 404
    assert client.post(BASE, json={'name': 'Ana', 'service_ids': [service.id]}).status_code == 422


def test_professional_validation_and_duplicate(client, login_as, tenant_user):
    login_as(tenant_user)
    for values in [{'name': ' '}, {'name': 'Ana', 'color': 'red'}, {'name': 'Ana', 'email': 'invalid'}, {'name': 'Ana', 'service_ids': ['abc']}]:
        assert client.post(BASE, json=values).status_code == 422
    values = {'name': 'Ana', 'email': 'ana@example.com'}
    assert client.post(BASE, json=values).status_code == 201
    assert client.post(BASE, json=values).status_code == 409


def test_professional_with_appointments_is_archived(client, login_as, tenant_user):
    customer, service, person = _schedule(tenant_user.company_id)
    login_as(tenant_user)
    response = client.post('/appointments', json={'customer_id': customer.id, 'service_id': service.id, 'professional_id': person.id, 'starts_at': _future_monday(10).isoformat()})
    assert response.status_code == 201
    assert client.post(f'{BASE}/{person.id}/delete', json={}).status_code == 200
    db.session.refresh(person)
    assert person.is_active is False
    assert person.appointments.count() == 1


def test_professional_mutations_require_admin(client, login_as, user_factory):
    user = user_factory(role='AGENT')
    login_as(user)
    assert client.post(BASE, json={'name': 'Ana'}).status_code == 403



def test_professional_form_multiple_services(client, login_as, tenant_user):
    from werkzeug.datastructures import MultiDict
    login_as(tenant_user)
    services = [Service(company_id=tenant_user.company_id, name=name) for name in ['Corte', 'Barba']]
    db.session.add_all(services)
    db.session.commit()
    response = client.post(BASE, data=MultiDict([('name', 'João'), ('service_ids', str(services[0].id)), ('service_ids', str(services[1].id))]), headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 201
    assert set(response.json['data']['service_ids']) == {item.id for item in services}
    assert 'João' in client.get('/appointments').text
