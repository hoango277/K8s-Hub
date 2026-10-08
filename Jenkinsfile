// CI only: this pipeline checks source code and never deploys to the cluster.
// Configure the Jenkins job as "Pipeline script from SCM" for the desired branch.
// The build agent needs Linux, Python 3.11+ with venv, Node.js 22+ and npm.
pipeline {
    agent any

    options {
        skipDefaultCheckout()
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        DEBUG = 'false'
        PYTHONUTF8 = '1'
        NEXT_TELEMETRY_DISABLED = '1'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Check build agent') {
            steps {
                script {
                    if (!isUnix()) {
                        error('This Jenkinsfile requires a Linux build agent.')
                    }
                }
                sh '''
                    set -eu
                    python3 --version
                    python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
                    node --version
                    node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)'
                    npm --version
                '''
            }
        }

        stage('Backend: install dependencies') {
            steps {
                sh '''
                    set -eu
                    python3 -m venv --clear .ci-venv
                    .ci-venv/bin/python -m pip install -r backend/requirements-dev.txt
                '''
            }
        }

        stage('Backend: lint') {
            steps {
                // Keep the build failed, but still collect unit-test results.
                catchError(buildResult: 'FAILURE', stageResult: 'FAILURE', catchInterruptions: false) {
                    sh '''
                        set -eu
                        cd backend
                        ../.ci-venv/bin/python -m ruff check app tests
                    '''
                }
            }
        }

        stage('Backend: unit tests') {
            steps {
                catchError(buildResult: 'FAILURE', stageResult: 'FAILURE', catchInterruptions: false) {
                    sh '''
                        set -eu
                        cd backend
                        ../.ci-venv/bin/python -m pytest -q tests/unit --junitxml="ci-unit-tests-${BUILD_NUMBER}.xml"
                    '''
                }
            }
        }

        stage('Frontend: lint, types and build') {
            steps {
                sh '''
                    set -eu
                    cd frontend
                    npm ci
                    npm run lint
                    npm run typecheck
                    npm run build
                '''
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: "backend/ci-unit-tests-${env.BUILD_NUMBER}.xml", allowEmptyArchive: true
        }
    }
}
