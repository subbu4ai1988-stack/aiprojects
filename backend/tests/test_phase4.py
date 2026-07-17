from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app

client=TestClient(app)


def login(email,password):
    with client:
        response=client.post('/api/auth/login',json={'email':email,'password':password})
    assert response.status_code==200
    return {'Authorization':f"Bearer {response.json()['access_token']}"}


def test_admin_rbac_assignments_and_dashboard_scope():
    admin=login('admin@recruitai.local','recruitai-admin')
    recruiter=login('recruiter@recruitai.local','recruitai')
    assert client.get('/api/admin/users',headers=recruiter).status_code==403
    suffix=uuid4().hex[:8]
    email=f'recruiter-{suffix}@example.com'
    password='temporary-pass'
    created=client.post('/api/admin/users',headers=admin,json={'email':email,'password':password,'role':'recruiter'})
    assert created.status_code==200
    new_user=created.json()
    new_recruiter=login(email,password)
    job=client.post('/api/jobs',headers=recruiter,json={'title':f'RBAC Role {suffix}','department':'Security','location':'Remote','description':'Test scoped job access for assigned recruiting users.'}).json()
    initial=client.get(f"/api/admin/jobs/{job['id']}/assignments",headers=admin).json()['user_ids']
    assert initial
    updated=client.put(f"/api/admin/jobs/{job['id']}/assignments",headers=admin,json={'user_ids':[new_user['id']]})
    assert updated.json()['user_ids']==[new_user['id']]
    old_visible={item['id'] for item in client.get('/api/jobs',headers=recruiter).json()}
    new_visible={item['id'] for item in client.get('/api/jobs',headers=new_recruiter).json()}
    assert job['id'] not in old_visible
    assert job['id'] in new_visible
    assert client.get(f"/api/jobs/{job['id']}/candidates",headers=recruiter).status_code==403
    assert client.get(f"/api/jobs/{job['id']}/candidates",headers=new_recruiter).status_code==200
    metrics=client.get('/api/dashboard/metrics',headers=new_recruiter)
    assert metrics.status_code==200
    assert metrics.json()['jobs']['total']>=1
    me=client.get('/api/me',headers=admin).json()
    assert me['role']=='admin'
