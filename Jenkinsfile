pipeline {
    agent any
    
    environment {
        PYTHONPATH = "${WORKSPACE}/src"
    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        
        stage('Setup Python Environment') {
            steps {
                script {
                    // Check if Python is available
                    sh 'python3 --version'
                    
                    // Create virtual environment
                    sh 'python3 -m venv venv'
                    
                    // Activate virtual environment and install dependencies
                    sh '''
                        source venv/bin/activate
                        pip install --upgrade pip
                        
                        # Install project dependencies
                        if [ -f requirements.txt ]; then
                            pip install -r requirements.txt
                        fi
                        
                        # Install test dependencies
                        if [ -f requirements-dev.txt ]; then
                            pip install -r requirements-dev.txt
                        fi
                    '''
                }
            }
        }
        
        stage('Static Code Analysis') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running ruff code analysis..."
                        if command -v ruff; then
                            ruff check . --exclude venv/*
                        else
                            echo "Ruff not found, skipping static analysis"
                        fi
                    '''
                }
            }
        }
        
        stage('Run Unit Tests') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running unit tests..."
                        python -m pytest tests/ -v --junit-xml=test-results.xml --cov=quant_trader --cov-report=html:coverage-report --cov-report=term-missing
                    '''
                }
            }
        }
        
        stage('Run Trader-Specific Tests') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Running trader-specific tests..."
                        python -m pytest tests/trader/ -v --junit-xml=test-results-trader.xml
                    '''
                }
            }
        }
        
        stage('Validate Trader Integration') {
            steps {
                script {
                    sh '''
                        source venv/bin/activate
                        echo "Validating trader integration..."
                        python -c "
from quant_trader.trader_loop import TraderLoop
from quant_trader.broker_base import BrokerAdapter
from quant_trader.execution_tracker import ExecutionTracker, EnhancedPositionManager
print('✓ Trader integration validated')
"
                    '''
                }
            }
        }
    }
    
    post {
        always {
            // Publish test results
            publishTestResults testResultsPattern: 'test-results.xml,test-results-trader.xml'
            
            // Archive coverage report
            archiveArtifacts artifacts: 'coverage-report/**/*', fingerprint: true, allowEmptyArchive: true
            
            // Publish coverage report
            publishCoverage adapters: [
                jacocoAdapter('coverage-report/*/coverage.xml')
            ], 
            sourceFileResolver: sourceFiles('STORE_LAST_BUILD')
        }
        
        success {
            script {
                echo "Pipeline completed successfully!"
                echo "Coverage report available at: ${env.BUILD_URL}artifact/coverage-report/index.html"
            }
        }
        
        failure {
            script {
                echo "Pipeline failed! Please check the logs for details."
                currentBuild.result = 'FAILURE'
            }
        }
        
        unstable {
            script {
                echo "Pipeline completed with some issues."
            }
        }
    }
}