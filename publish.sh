rm deployable.zip
cd lambda
zip -X -r deployable.zip *
mv deployable.zip ./../
cd ..
aws lambda update-function-code --function-name paper-a-day --zip-file fileb://deployable.zip

